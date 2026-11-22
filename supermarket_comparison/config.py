"""Application configuration.

Settings are read from environment variables prefixed with ``SUPERMARKET_``
(e.g. ``SUPERMARKET_DEBUG=1``). No extra dependency such as
``pydantic-settings`` is required.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Final, get_origin

from pydantic import BaseModel, ConfigDict, Field

ENV_PREFIX: Final = "SUPERMARKET_"

#: Additional unprefixed environment names accepted for the Marktguru keys,
#: matching the header names used by the public web client.
_ENV_ALIASES: Final[dict[str, str]] = {
    # Short names documented in the deployment guide; the SUPERMARKET_-prefixed
    # form always wins when both are set.
    "stealth_mode": "STEALTH_MODE",
    "site_password": "SITE_PASSWORD",
    "session_secret": "SESSION_SECRET",
    "admin_password": "ADMIN_PASSWORD",
    "trust_proxy": "TRUST_PROXY",
    "max_upload_bytes": "MAX_UPLOAD_BYTES",
    "vision_primary_provider": "VISION_PRIMARY_PROVIDER",
    "vision_primary_api_key": "VISION_PRIMARY_API_KEY",
    "vision_primary_model": "VISION_PRIMARY_MODEL",
    "vision_fallback_provider": "VISION_FALLBACK_PROVIDER",
    "vision_fallback_api_key": "VISION_FALLBACK_API_KEY",
    "vision_fallback_model": "VISION_FALLBACK_MODEL",
    "max_scans_per_day_per_ip": "MAX_SCANS_PER_DAY_PER_IP",
    "max_global_scans_per_day": "MAX_GLOBAL_SCANS_PER_DAY",
    "turnstile_site_key": "TURNSTILE_SITE_KEY",
    "turnstile_secret_key": "TURNSTILE_SECRET_KEY",
}


#: Names from the previous iteration that still resolve.
_LEGACY_ALIASES: Final[dict[str, str]] = {}


class Settings(BaseModel):
    """Runtime configuration for the API and the scraper clients."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    app_name: str = "DACH Supermarket Price Comparison API"
    app_version: str = "0.1.0"
    debug: bool = False
    api_prefix: str = ""

    #: Comma-separated CORS origins (default: * for dev).
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])

    http_timeout: float = 15.0
    http_user_agent: str = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 "
        "SupermarketComparison/0.1"
    )
    cache_ttl_seconds: int = 300

    default_country: str = "DE"
    default_language: str = "de-DE"
    default_postal_code: str | None = None

    # --- storage ---------------------------------------------------------
    #: SQLite file for price history and anonymised search statistics.
    database_path: str = "data/supermarkt.db"

    # --- limits ----------------------------------------------------------
    #: Hard ceiling for result lists (100 entries per page, so
    #: large requests are served by paging).
    max_results: int = 1000
    #: Default page size used by the UI/API when no limit is given.
    default_results: int = 50

    # --- standard prices (permanent assortment) --------------------------
    #: Open Prices has no German supermarket coverage yet, so this stays
    #: opt-in per request; the UI exposes it as "Gesamtes Sortiment".
    standard_prices_enabled: bool = True
    openfoodfacts_search_url: str = "https://search.openfoodfacts.org"
    openprices_base_url: str = "https://prices.openfoodfacts.org"
    standard_price_cache_ttl: int = 3600

    # --- stealth / access gate -------------------------------------------
    #: While true: noindex headers, robots.txt disallow-all, and the password
    #: gate below is enforced when a password is set.
    stealth_mode: bool = True
    site_password: str | None = None
    #: Stable secret for the login cookie. Derived from the password when unset.
    session_secret: str | None = None
    #: Strong password for admin/system endpoints (fail-closed: when unset,
    #: admin and moderation endpoints are disabled).
    admin_password: str | None = None
    #: Comma-separated list of trusted proxy headers for rate limiting
    #: (only honoured when `trust_proxy` is true).
    trust_proxy: bool = False

    standard_price_limit: int = 12

    # --- receipt vision (Phase 2) ----------------------------------------
    #: Max. size of an uploaded receipt photo/PDF in bytes.
    max_upload_bytes: int = 3 * 1024 * 1024
    #: Max. width (px) for client-side canvas downscaling.
    vision_max_width: int = 1200
    #: JPEG quality for re-encoding and client compression.
    vision_jpeg_quality: int = 82
    #: Primary provider: gemini | mistral | openai_compatible (empty = off).
    vision_primary_provider: str = ""
    vision_primary_api_key: str = ""
    vision_primary_model: str = ""
    #: Optional fallback provider (same enums).
    vision_fallback_provider: str = ""
    vision_fallback_api_key: str = ""
    vision_fallback_model: str = ""
    #: Base URL for ``openai_compatible`` providers (e.g. local llama.cpp).
    vision_openai_base_url: str = "https://api.openai.com/v1"
    #: Max. items a single receipt may carry (schema guard).
    vision_max_items: int = 120
    #: Scan budget per IP.
    max_scans_per_day_per_ip: int = 15
    #: Global server-funded scan budget per day.
    max_global_scans_per_day: int = 500

    # --- Cloudflare Turnstile (optional) ----------------------------------
    turnstile_site_key: str = ""
    turnstile_secret_key: str = ""


    @classmethod
    def from_env(cls) -> Settings:
        """Build settings from ``SUPERMARKET_*`` environment variables."""

        values: dict[str, Any] = {}
        for name, field in cls.model_fields.items():
            raw = os.getenv(f"{ENV_PREFIX}{name.upper()}")
            if raw is None or not raw.strip():
                # Allow the short Marktguru names used by the web client.
                alias = _ENV_ALIASES.get(name)
                raw = os.getenv(alias) if alias else None
                legacy = _LEGACY_ALIASES.get(name)
                if (raw is None or not raw.strip()) and legacy:
                    raw = os.getenv(legacy)
            if raw is None or not raw.strip():
                continue
            raw = raw.strip()

            annotation = field.annotation
            if annotation is bool:
                values[name] = raw.lower() in {"1", "true", "yes", "on"}
            elif annotation is int:
                try:
                    values[name] = int(raw)
                except ValueError:
                    continue
            elif annotation is float:
                try:
                    values[name] = float(raw)
                except ValueError:
                    continue
            elif annotation is list[str] or get_origin(annotation) is list:
                values[name] = [part.strip() for part in raw.split(",") if part.strip()]
            else:
                values[name] = raw

        return cls(**values)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached application settings."""

    return Settings.from_env()


#: Convenience singleton for modules that only need to read configuration.
settings: Settings = get_settings()

__all__ = ["ENV_PREFIX", "Settings", "get_settings", "settings"]
