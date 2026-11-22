"""Optional Cloudflare Turnstile bot protection for receipt scanning.

The widget is only enforced when ``TURNSTILE_SITE_KEY`` **and**
``TURNSTILE_SECRET_KEY`` are configured.  When they are empty (local dev,
self-hosters) the check is skipped cleanly so the app stays usable without a
Cloudflare account.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..config import get_settings

logger = logging.getLogger(__name__)

#: Cloudflare siteverify endpoint.
_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def is_turnstile_enabled() -> bool:
    """True only when both site and secret keys are configured."""

    settings = get_settings()
    return bool(settings.turnstile_site_key and settings.turnstile_secret_key)


async def verify_turnstile(token: str | None, *, remote_ip: str | None = None) -> bool:
    """Verify a Turnstile token against Cloudflare.

    Returns ``True`` when the check is disabled (no keys) or the token is
    valid.  Never raises — a verification failure just denies the request.
    """

    if not is_turnstile_enabled():
        return True
    if not token:
        return False

    settings = get_settings()
    payload: dict[str, Any] = {
        "secret": settings.turnstile_secret_key,
        "response": token,
    }
    if remote_ip:
        payload["remoteip"] = remote_ip

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.post(_VERIFY_URL, data=payload)
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError) as exc:  # pragma: no cover - defensive
        logger.warning("Turnstile verification failed: %s", exc)
        return False

    if not isinstance(data, dict) or not data.get("success"):
        codes = data.get("error-codes") or []
        if codes:
            logger.debug("Turnstile rejected token: %s", codes)
        return False
    return True


__all__ = ["is_turnstile_enabled", "verify_turnstile"]
