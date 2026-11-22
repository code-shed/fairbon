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
import secrets
import time
from typing import Final

from fastapi import Request, Response

from ..config import Settings

COOKIE_NAME: Final = "spv_session"
#: How long a login stays valid (seconds): 30 days.
SESSION_TTL: Final = 60 * 60 * 24 * 30

#: Paths that bypass the gate entirely.
PUBLIC_PATHS: Final = frozenset({"/health", "/login", "/logout", "/robots.txt"})


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
    """Whether *path* is an admin-only area (prefix match for sub-routes)."""

    for prefix in ADMIN_PATHS:
        if path == prefix or path.startswith(prefix + "/"):
            return True
        # routers may be mounted under SUPERMARKET_API_PREFIX
        if path.endswith(prefix) or path.endswith(prefix + "/"):
            return True
        if (prefix + "/") in path:
            return True
    return False


def is_admin_authenticated(request: Request, settings: Settings) -> bool:
    """Constant-time admin check via Basic auth (no cookie for the admin)."""

    return admin_password_matches(settings, basic_password(request))


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
    return (
        path in PUBLIC_PATHS or path.startswith("/docs") or path.startswith("/openapi")
    )


def set_session_cookie(response: Response, settings: Settings) -> None:
    response.set_cookie(
        COOKIE_NAME,
        issue_token(settings),
        max_age=SESSION_TTL,
        httponly=True,
        samesite="lax",
        secure=False,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def random_secret() -> str:
    """Convenience for ``.env`` generation."""

    return secrets.token_urlsafe(32)


__all__ = [
    "ADMIN_PATHS",
    "COOKIE_NAME",
    "PUBLIC_PATHS",
    "SESSION_TTL",
    "admin_password_matches",
    "basic_password",
    "clear_session_cookie",
    "is_admin_authenticated",
    "is_admin_path",
    "is_authenticated",
    "is_public_path",
    "issue_token",
    "password_matches",
    "random_secret",
    "set_session_cookie",
    "token_is_valid",
]
