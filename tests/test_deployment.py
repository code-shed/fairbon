"""Static checks for the hardened production deployment (Phase 4)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


# -- Dockerfile ------------------------------------------------------------


def test_dockerfile_copies_the_pwa_frontend() -> None:
    dockerfile = _read("Dockerfile")

    assert "COPY frontend ./frontend" in dockerfile
    assert "SUPERMARKET_FRONTEND_DIR=/app/frontend" in dockerfile


def test_dockerfile_runs_as_non_root_user() -> None:
    dockerfile = _read("Dockerfile")

    assert "useradd --uid 1000" in dockerfile
    assert "\nUSER app" in dockerfile
    assert "\nUSER root" not in dockerfile


def test_dockerfile_has_a_healthcheck() -> None:
    dockerfile = _read("Dockerfile")

    assert "HEALTHCHECK" in dockerfile
    assert "/health" in dockerfile


# -- docker-compose --------------------------------------------------------


def test_compose_binds_only_to_localhost() -> None:
    compose = _read("docker-compose.yml")

    assert '127.0.0.1:8000:8000' in compose
    assert '"8000:8000"' not in compose


def test_compose_applies_resource_and_privilege_limits() -> None:
    compose = _read("docker-compose.yml")

    assert "mem_limit: 512m" in compose
    assert "read_only: true" in compose
    assert "no-new-privileges:true" in compose
    assert "cap_drop:" in compose
    assert "restart: unless-stopped" in compose


def test_compose_keeps_the_database_on_a_bind_mount() -> None:
    compose = _read("docker-compose.yml")

    assert "./data:/app/data" in compose
    assert "SUPERMARKET_DATABASE_PATH: /app/data/supermarkt.db" in compose


# -- .dockerignore / .env.example -----------------------------------------


def test_dockerignore_excludes_secrets_and_data() -> None:
    ignore = _read(".dockerignore")

    for pattern in (".env", "data", "*.db", ".venv", "tests"):
        assert pattern in ignore
    assert "frontend" not in ignore.split()


def test_env_example_documents_all_new_variables() -> None:
    env = _read(".env.example")

    for name in (
        "ADMIN_PASSWORD",
        "SUPERMARKET_CORS_ORIGINS",
        "TRUST_PROXY",
        "MAX_SCANS_PER_DAY_PER_IP",
        "MAX_GLOBAL_SCANS_PER_DAY",
        "MAX_UPLOAD_BYTES",
        "VISION_PRIMARY_PROVIDER",
        "VISION_FALLBACK_PROVIDER",
        "VISION_OPENAI_BASE_URL",
        "TURNSTILE_SITE_KEY",
        "TURNSTILE_SECRET_KEY",
    ):
        assert name in env, name
    # Removed in V1.0 (no scraping):
    assert "HARVEST_" not in env
    assert "KAUFDA_" not in env


# -- security guide --------------------------------------------------------


def test_security_deployment_guide_covers_the_hardening_steps() -> None:
    guide = _read("SECURITY_DEPLOYMENT.md")

    for needle in (
        "request_body",
        "max_size 3MB",
        "ufw",
        "fail2ban",
        "UptimeRobot",
        "ADMIN_PASSWORD",
        "Turnstile",
        "backup",
        "127.0.0.1:8000",
    ):
        assert needle.lower() in guide.lower(), needle


# -- admin/ moderation path protection ------------------------------------


def test_moderation_routes_are_admin_protected() -> None:
    from supermarket_comparison.services.auth import is_admin_path

    assert is_admin_path("/api/v1/crowd/prices/abc/approve") is True
    assert is_admin_path("/api/v1/crowd/prices/abc/reject") is True
    assert is_admin_path("/v2/api/v1/crowd/prices/abc/approve") is True
    assert is_admin_path("/api/v1/crowd/review") is True
    assert is_admin_path("/api/v1/crowd/review/approve-all") is True
    # Public community endpoints stay public:
    assert is_admin_path("/api/v1/crowd/prices") is False
    assert is_admin_path("/api/v1/crowd/prices/abc/confirm") is False
    assert is_admin_path("/api/v1/crowd/coverage") is False
