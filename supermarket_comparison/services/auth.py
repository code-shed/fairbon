"""Password gate for the build-up phase (stealth mode).

Two ways in:

* the browser posts the password to ``/login`` and receives a signed session
  cookie (HMAC-SHA256 over an expiry timestamp);
* API clients send HTTP Basic auth (any username, the configured password).

If ``SITE_PASSWORD`` is empty the whole gate is disabled and the site is
public. ``/health`` always stays reachable for monitoring.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import time
from typing import Final

from fastapi import Request, Response

from ..config import Settings

COOKIE_NAME: Final = "spv_session"
ADMIN_COOKIE_NAME: Final = "spv_admin_session"
#: How long a login stays valid (seconds): 30 days.
SESSION_TTL: Final = 60 * 60 * 24 * 30
#: Short-lived admin session (12 h) for the dedicated admin login view.
ADMIN_SESSION_TTL: Final = 60 * 60 * 12

#: Paths that bypass the gate entirely.
PUBLIC_PATHS: Final = frozenset(
    {
        "/health",
        "/login",
        "/logout",
        "/robots.txt",
        # Manifest and worker carry only app branding / the public shell
        # cache list; browsers fetch them without cookies.
        "/manifest.webmanifest",
        "/sw.js",
    }
)


def _uses_https(settings: Settings, request: Request | None) -> bool:
    """TLS detection: direct scheme, or trusted forwarding header."""

    if request is None:
        return False
    if request.url.scheme == "https":
        return True
    if settings.trust_proxy:
        return (request.headers.get("x-forwarded-proto") or "").lower() == "https"
    return False


def _secret(settings: Settings) -> bytes:
    raw = settings.session_secret or ""
    if not raw:
        raw = "spv|" + (settings.site_password or "public")
    return hashlib.sha256(raw.encode("utf-8")).digest()


def issue_token(settings: Settings, *, now: float | None = None) -> str:
    """Return ``"<expiry>.<signature>"`` for a fresh login."""

    expiry = int((now if now is not None else time.time()) + SESSION_TTL)
    payload = str(expiry)
    signature = hmac.new(
        _secret(settings), payload.encode(), hashlib.sha256
    ).hexdigest()
    return f"{expiry}.{signature}"


def token_is_valid(
    settings: Settings, token: str | None, *, now: float | None = None
) -> bool:
    if not settings.site_password:
        return True
    if not token or "." not in token:
        return False
    expiry_text, signature = token.split(".", 1)
    try:
        expiry = int(expiry_text)
    except ValueError:
        return False
    if expiry < (now if now is not None else time.time()):
        return False
    expected = hmac.new(
        _secret(settings), expiry_text.encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def password_matches(settings: Settings, candidate: str | None) -> bool:
    if not settings.site_password:
        return True
    if candidate is None:
        return False
    return hmac.compare_digest(settings.site_password, candidate)


def _admin_secret(settings: Settings) -> bytes:
    raw = "admin|" + (settings.admin_password or settings.session_secret or "public")
    return hashlib.sha256(raw.encode("utf-8")).digest()


def issue_admin_token(settings: Settings, *, now: float | None = None) -> str:
    expiry = int((now if now is not None else time.time()) + ADMIN_SESSION_TTL)
    payload = str(expiry)
    signature = hmac.new(
        _admin_secret(settings), payload.encode(), hashlib.sha256
    ).hexdigest()
    return f"{expiry}.{signature}"


def admin_token_is_valid(
    settings: Settings, token: str | None, *, now: float | None = None
) -> bool:
    if not settings.admin_password or not token or "." not in token:
        return False
    expiry_text, signature = token.split(".", 1)
    try:
        expiry = int(expiry_text)
    except ValueError:
        return False
    if expiry < (now if now is not None else time.time()):
        return False
    expected = hmac.new(
        _admin_secret(settings), expiry_text.encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def admin_password_matches(settings: Settings, candidate: str | None) -> bool:
    """Constant-time comparison of an admin password candidate.

    Admin endpoints are fail-closed: without ``ADMIN_PASSWORD`` set they are
    disabled and no candidate ever matches.
    """

    if not settings.admin_password:
        return False
    if candidate is None:
        return False
    return hmac.compare_digest(settings.admin_password, candidate)


#: Paths guarded by ``ADMIN_PASSWORD`` (fail-closed). The site password
#: gate (``SITE_PASSWORD``) still applies on top for every non-public path.
ADMIN_PATHS: Final = frozenset(
    {
        "/admin",
        "/api/v1/system/backup-db",
        "/api/v1/system/restore-db",
        "/api/v1/crowd/review",
        "/api/v1/crowd/approve",
        "/api/v1/crowd/reject",
        "/api/v1/crowd/approve-all",
        "/api/v1/admin/database",
    }
)


def is_admin_path(path: str) -> bool:
    """Whether *path* is an admin-only area (exact paths and sub-routes)."""

    # The dedicated login view must stay reachable without an admin session.
    if path.rstrip("/") == "/admin/login":
        return False
    for prefix in ADMIN_PATHS:
        if path == prefix or path.startswith(prefix + "/"):
            return True
        # Routers may be mounted under a configurable API prefix.
        if path.endswith(prefix) or path.endswith(prefix.rstrip("/") + "/"):
            return True
    # Moderation of a specific price, optionally behind an arbitrary prefix.
    return bool(re.search(r"/crowd/prices/[^/]+/(approve|reject)/?$", path))


def basic_password(request: Request) -> str | None:
    """Extract the password from an ``Authorization: Basic`` header."""

    header = request.headers.get("authorization") or ""
    scheme, _, encoded = header.partition(" ")
    if scheme.lower() != "basic" or not encoded:
        return None
    try:
        decoded = base64.b64decode(encoded).decode("utf-8", errors="replace")
    except (ValueError, UnicodeDecodeError):
        return None
    _, _, password = decoded.partition(":")
    return password


def is_authenticated(request: Request, settings: Settings) -> bool:
    if not settings.site_password:
        return True
    if token_is_valid(settings, request.cookies.get(COOKIE_NAME)):
        return True
    return password_matches(settings, basic_password(request))


def is_public_path(path: str) -> bool:
    """Paths reachable without the site password (health, login, static)."""

    return path in PUBLIC_PATHS


def set_session_cookie(
    response: Response, settings: Settings, request: Request | None = None
) -> None:
    response.set_cookie(
        COOKIE_NAME,
        issue_token(settings),
        max_age=SESSION_TTL,
        httponly=True,
        samesite="lax",
        secure=_uses_https(settings, request),
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def is_admin_authenticated(request: Request, settings: Settings) -> bool:
    """Admin session cookie or Basic auth — both use constant-time checks."""

    return admin_token_is_valid(
        settings, request.cookies.get(ADMIN_COOKIE_NAME)
    ) or admin_password_matches(settings, basic_password(request))


def set_admin_session_cookie(
    response: Response, settings: Settings, request: Request | None = None
) -> None:
    response.set_cookie(
        ADMIN_COOKIE_NAME,
        issue_admin_token(settings),
        max_age=ADMIN_SESSION_TTL,
        httponly=True,
        samesite="strict",
        secure=_uses_https(settings, request),
        path="/",
    )


def clear_admin_session_cookie(response: Response) -> None:
    response.delete_cookie(ADMIN_COOKIE_NAME, path="/")


def random_secret() -> str:
    """Convenience for ``.env`` generation."""

    return secrets.token_urlsafe(32)


__all__ = [
    "ADMIN_COOKIE_NAME",
    "ADMIN_PATHS",
    "ADMIN_SESSION_TTL",
    "COOKIE_NAME",
    "PUBLIC_PATHS",
    "SESSION_TTL",
    "admin_password_matches",
    "admin_token_is_valid",
    "basic_password",
    "clear_admin_session_cookie",
    "clear_session_cookie",
    "is_admin_authenticated",
    "is_admin_path",
    "is_authenticated",
    "is_public_path",
    "issue_admin_token",
    "issue_token",
    "password_matches",
    "random_secret",
    "set_admin_session_cookie",
    "set_session_cookie",
    "token_is_valid",
]
