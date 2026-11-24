"""Regression tests for the pre-deployment hardening audit (H1-H4, M1-M11)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import Response

from supermarket_comparison.api.main import create_app
from supermarket_comparison.config import Settings, get_settings
from supermarket_comparison.services import auth

ROOT = Path(__file__).resolve().parents[1]

STATE_KEYS = (
    "site_password",
    "admin_password",
    "session_secret",
    "trust_proxy",
    "stealth_mode",
)


@pytest.fixture()
def restore_settings() -> Iterator[dict[str, object]]:
    settings = get_settings()
    previous = {key: getattr(settings, key) for key in STATE_KEYS}
    yield previous  # type: ignore[misc]
    for key, value in previous.items():
        object.__setattr__(settings, key, value)


def _request(
    scheme: str = "http", headers: list[tuple[bytes, bytes]] | None = None
) -> Request:
    return Request(
        {
            "type": "http",
            "scheme": scheme,
            "server": ("testserver", 80 if scheme == "http" else 443),
            "headers": headers or [],
            "method": "GET",
            "path": "/",
            "query_string": b"",
        }
    )


# -- H1 --------------------------------------------------------------------


def test_short_vision_openai_base_url_is_read_by_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in ("SUPERMARKET_VISION_OPENAI_BASE_URL", "VISION_OPENAI_BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("VISION_OPENAI_BASE_URL", "http://127.0.0.1:11434/v1")

    assert Settings.from_env().vision_openai_base_url == "http://127.0.0.1:11434/v1"


# -- H4 --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("scheme", "headers", "secure"),
    [
        ("http", None, False),
        ("https", None, True),
        (
            "http",
            [(b"x-forwarded-proto", b"https")],
            True,
        ),
    ],
)
def test_session_cookie_secure_flag_follows_request_scheme(
    restore_settings: dict[str, object], scheme: str, headers: list | None, secure: bool
) -> None:
    settings = get_settings()
    object.__setattr__(settings, "site_password", "site-secret")
    object.__setattr__(settings, "session_secret", "session-secret")
    object.__setattr__(settings, "trust_proxy", bool(headers))
    response = Response()
    auth.set_session_cookie(response, settings, request=_request(scheme, headers))

    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert ("secure" in cookie) is secure


def test_docs_and_openapi_are_gated_with_site_password(
    restore_settings: dict[str, object],
) -> None:
    settings = get_settings()
    object.__setattr__(settings, "site_password", "site-secret")
    with TestClient(create_app()) as client:
        assert client.get("/docs").status_code in (401, 303)
        assert client.get("/openapi.json").status_code in (401, 303)


def test_admin_path_detection_has_no_substring_matches() -> None:
    assert auth.is_admin_path("/admin") is True
    assert auth.is_admin_path("/admin/login") is False
    assert auth.is_admin_path("/api/v1/admin/database") is True
    assert auth.is_admin_path("/api/v1/crowd/prices/abc/approve") is True
    assert auth.is_admin_path("/api/v1/crowd/prices/abc/confirm") is False
    assert auth.is_admin_path("/my/admin/dashboard") is False
    assert auth.is_admin_path("/api/v1/crowd/coverage") is False


# -- M1 --------------------------------------------------------------------


def test_admin_login_grants_a_session_and_unlocks_admin(
    restore_settings: dict[str, object],
) -> None:
    settings = get_settings()
    object.__setattr__(settings, "site_password", "")
    object.__setattr__(settings, "admin_password", "admin-secret")
    with TestClient(create_app()) as client:
        login = client.post(
            "/admin/login", data={"password": "admin-secret"}, follow_redirects=False
        )
        assert login.status_code == 303
        assert auth.ADMIN_COOKIE_NAME in client.cookies
        assert client.get("/admin").status_code == 200

        bad = client.post(
            "/admin/login", data={"password": "wrong"}, follow_redirects=False
        )
        assert bad.status_code == 303
        assert client.get("/admin/login").status_code == 200


def test_admin_session_cookie_is_hardened(restore_settings: dict[str, object]) -> None:
    settings = get_settings()
    object.__setattr__(settings, "admin_password", "admin-secret")
    with TestClient(create_app()) as client:
        response = client.post(
            "/admin/login", data={"password": "admin-secret"}, follow_redirects=False
        )
        raw = response.headers["set-cookie"].lower()
        assert auth.ADMIN_COOKIE_NAME.lower() in raw
        assert "httponly" in raw and "samesite=strict" in raw
        token = client.cookies.get(auth.ADMIN_COOKIE_NAME)
        assert auth.admin_token_is_valid(settings, token)


def test_admin_link_is_removed_from_user_interfaces() -> None:
    shell = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
    legacy = (ROOT / "supermarket_comparison/api/templates/index.html").read_text(
        encoding="utf-8"
    )
    assert 'href="/admin"' not in shell
    assert 'id="admin-open"' not in legacy
    assert "Admin-Zugang" in (ROOT / "SECURITY_DEPLOYMENT.md").read_text(
        encoding="utf-8"
    )


# -- H3 --------------------------------------------------------------------


def test_service_worker_never_caches_protected_or_api_paths() -> None:
    sw = (ROOT / "frontend/sw.js").read_text(encoding="utf-8")
    paths = ("/admin", "/login", "/logout", "/impressum", "/datenschutz", "/health")
    for path in paths:
        assert f'"{path}"' in sw, path
    assert 'url.pathname.indexOf("/api/")' in sw
    assert 'event.request.method !== "GET"' in sw
    assert "no-store" in sw and "no-cache" in sw
    assert "networkFirst" in sw
    assert "CACHE_ONLY_ASSETS" in sw


# -- M2 / M3 ---------------------------------------------------------------


def test_privacy_text_matches_timestamps_and_ocr_tempfiles() -> None:
    import asyncio

    from supermarket_comparison.api.routes.legal import datenschutz

    html = " ".join(asyncio.run(datenschutz()).body.decode().split())
    assert "ohne genaue Uhrzeit des Kassenbons" in html
    assert "technische Erfassungszeitpunkt" in html
    assert "vorübergehend angelegte temporäre Arbeitsdateien" in html
    assert "nach der Texterkennung wieder gelöscht" in html


# -- M4 --------------------------------------------------------------------


def test_undo_toasts_announce_the_pending_deletion() -> None:
    receipts = (ROOT / "frontend/js/views/receipts.js").read_text(encoding="utf-8")
    listing = (ROOT / "frontend/js/views/list.js").read_text(encoding="utf-8")
    assert "Bon wird in 5 Sekunden gelöscht – Rückgängig" in receipts
    assert "Merkliste wird in 5 Sekunden geleert – Rückgängig" in listing


# -- M5-M11 + low ----------------------------------------------------------


def test_ci_and_container_hardening_artifacts() -> None:
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    for needle in (
        "uv sync --frozen",
        "uv run ruff check .",
        "uv run pytest -q",
        "scripts/check_secrets.py",
        "docker compose config -q",
    ):
        assert needle in ci, needle

    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM python:3.12.16-slim-bookworm@sha256:" in dockerfile
    assert "ghcr.io/astral-sh/uv:0.13.7@sha256:" in dockerfile
    assert ":latest" not in dockerfile

    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert 'cpus: "1.0"' in compose
    assert 'driver: "json-file"' in compose
    assert '"10m"' in compose and '"5"' in compose


def test_deployment_guide_covers_ops_hardening() -> None:
    guide = (ROOT / "SECURITY_DEPLOYMENT.md").read_text(encoding="utf-8")
    for needle in (
        "apt install -y caddy",
        "jail.local",
        "chmod 600 data/supermarkt.db",
        "OnCalendar=daily",
        "--netrc-file",
        "request_body {",
        "Admin-Zugang",
        "unsafe-inline",
        "logrotate",
    ):
        assert needle in guide, needle
    assert "max_body_size 3MB" not in guide


def test_csp_unknown_state_is_documented() -> None:
    main = (ROOT / "supermarket_comparison/api/main.py").read_text(encoding="utf-8")
    guide = (ROOT / "SECURITY_DEPLOYMENT.md").read_text(encoding="utf-8")
    assert "'unsafe-inline'" in main
    assert "nicht entfernt" in guide


def test_small_ux_consistency_fixes() -> None:
    html = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
    sheet = (ROOT / "frontend/js/components/add-sheet.js").read_text(encoding="utf-8")
    css = (ROOT / "frontend/css/styles.css").read_text(encoding="utf-8")
    migration = (ROOT / "docs/MIGRATION.md").read_text(encoding="utf-8")
    deploy_server = (ROOT / "DEPLOY_SERVER.md").read_text(encoding="utf-8")

    assert "Excel-Export (.xlsx)" in html and "CSV / Excel" not in html
    assert r"/\.txt$/i" in sheet
    assert "min-width: 44px; min-height: 44px" in css
    assert "min-height: 44px; color: var(--muted)" in css
    assert "sudo chown -R 1000:1000 data" in migration
    assert "sudo chown -R 1000:1000 data" in deploy_server
