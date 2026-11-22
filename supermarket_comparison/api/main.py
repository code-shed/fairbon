"""FastAPI application factory and ASGI entry point."""

from __future__ import annotations

import inspect
import logging
import math
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from importlib import resources
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles

from ..config import get_settings
from ..services.aggregator import Aggregator
from ..services.auth import (
    clear_session_cookie,
    is_admin_authenticated,
    is_admin_path,
    is_authenticated,
    is_public_path,
    password_matches,
    set_session_cookie,
)
from ..services.rate_limit import allow_read
from .deps import get_aggregator
from .routes import (
    admin_db,
    basket,
    crowd,
    export as export_router,
    history,
    images,
    products,
    receipts as receipts_router,
    stores,
    system,
)

logger = logging.getLogger(__name__)

DESCRIPTION = """
Community-based price comparison for the DACH region. Prices are contributed
anonymously by users via receipt scanning — no scraping, no ad-tracking.

* ``/`` – German-language search UI
* ``/api/v1/products/search`` – search offers across stores
* ``/api/v1/products/search/ranked`` – search with relevance tiers + filters
* ``/api/v1/products/compare`` – cheapest offer per store for one product
* ``/api/v1/basket/optimize`` – cheapest split for a shopping list
* ``/api/v1/stores/search`` – branches near a postal code
* ``/api/v1/crowd/*`` – anonymous community prices and receipt import

Interactive documentation is available at `/docs` (Swagger UI) and
`/redoc` (ReDoc).
"""

TAGS_METADATA = [
    {
        "name": "products",
        "description": "Search, compare and normalise product offers.",
    },
    {
        "name": "stores",
        "description": "Look up physical supermarket branches by postal code.",
    },
    {
        "name": "basket",
        "description": "Optimise a shopping list across stores.",
    },
    {
        "name": "system",
        "description": "Health check and service metadata.",
    },
]

_TEMPLATES_DIR = "templates"
_INDEX_FILE = "index.html"


LOGIN_HTML = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Anmeldung · Supermarkt-Preisvergleich</title>
<style>
  :root {
    --bg:#f6f7f5; --surface:#fff; --text:#191d1a; --muted:#5b6560;
    --line:#dfe3dd; --accent:#0f6b46; --danger:#a5271d;
  }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#0e1110; --surface:#161a18; --text:#e9eee9; --muted:#9aa8a0;
            --line:#2a302c; --accent:#3fc284; --danger:#ff9188; }
  }
  * { box-sizing: border-box; }
  body {
    margin:0; min-height:100dvh; display:grid; place-items:center;
    background:var(--bg); color:var(--text); padding:24px;
    font:16px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  }
  main {
    width:min(420px, 100%); background:var(--surface);
    border:1px solid var(--line); border-radius:16px; padding:28px 26px;
  }
  h1 {
    margin:0 0 6px; font:600 1.55rem/1.2 ui-serif, Georgia, serif;
    letter-spacing:-.02em;
  }
  p { margin:0 0 18px; color:var(--muted); font-size:.9rem; }
  label { display:block; font-size:.78rem; font-weight:600; letter-spacing:.04em;
          text-transform:uppercase; color:var(--muted); margin-bottom:6px; }
  input {
    width:100%; padding:12px 14px; font:inherit; color:var(--text);
    background:var(--bg); border:1px solid var(--line); border-radius:10px;
  }
  input:focus-visible, button:focus-visible {
    outline:2px solid var(--accent); outline-offset:2px;
  }
  button {
    margin-top:16px; width:100%; padding:12px 18px; font:inherit; font-weight:650;
    color:#fff; background:var(--accent); border:1px solid transparent;
    border-radius:10px; cursor:pointer;
  }
  .error { color:var(--danger); font-size:.88rem; margin:12px 0 0; }
  .hint { margin:16px 0 0; font-size:.78rem; color:var(--muted); }
</style>
</head>
<body>
<main>
  <h1>Supermarkt-Preisvergleich</h1>
  <p>Diese Seite ist während der Aufbauphase geschützt. Bitte Passwort eingeben.</p>
  <form method="post" action="/login">
    <input type="hidden" name="next" value="__NEXT__">
    <label for="password">Passwort</label>
    <input id="password" name="password" type="password" autocomplete="current-password"
           autofocus required>
    __ERROR__
    <button type="submit">Anmelden</button>
  </form>
  <p class="hint">
    Tipp: API-Clients nutzen HTTP Basic Auth (beliebiger Benutzername).
  </p>
</main>
</body>
</html>"""


def _login_html(*, next_path: str, error: bool) -> str:
    safe_next = (
        next_path
        if next_path.startswith("/") and not next_path.startswith("//")
        else "/"
    )
    message = (
        '<p class="error">Passwort falsch. Bitte erneut versuchen.</p>' if error else ""
    )
    return LOGIN_HTML.replace("__NEXT__", safe_next).replace("__ERROR__", message)


@lru_cache(maxsize=1)
def load_admin_html() -> str:
    """Return the admin database dashboard (``templates/admin.html``)."""

    try:
        template = resources.files("supermarket_comparison.api") / _TEMPLATES_DIR
        return (template / "admin.html").read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError, NotADirectoryError):
        path = Path(__file__).with_name(_TEMPLATES_DIR) / "admin.html"
        return path.read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def _frontend_dir() -> Path:
    """Resolve the static frontend directory (repo root or packaged)."""

    import os

    override = os.getenv("SUPERMARKET_FRONTEND_DIR")
    if override:
        candidate = Path(override)
        if candidate.is_dir():
            return candidate
    # main.py -> api -> supermarket_comparison -> repo root
    candidate = Path(__file__).resolve().parents[2] / "frontend"
    if candidate.is_dir():
        return candidate
    packaged = Path(__file__).resolve().parent / "frontend"
    return packaged


def load_frontend_shell() -> str:
    """Return the modular frontend shell (``frontend/index.html``)."""

    path = _frontend_dir() / "index.html"
    if path.is_file():
        return path.read_text(encoding="utf-8")
    # Fallback: the legacy single-file template.
    return load_index_html()


def load_index_html() -> str:
    """Return the single-page search UI (``api/templates/index.html``).

    ``importlib.resources`` is used first so the template is found when the
    project is installed as a wheel; the plain path read keeps it working
    from a source checkout without installation.
    """

    try:
        template = resources.files("supermarket_comparison.api") / _TEMPLATES_DIR
        return (template / _INDEX_FILE).read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError, NotADirectoryError):
        path = Path(__file__).with_name(_TEMPLATES_DIR) / _INDEX_FILE
        return path.read_text(encoding="utf-8")


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Clean up resources on shutdown — no periodic tasks."""

    repository = getattr(app.state, "repository", None)
    try:
        yield
    finally:
        aggregator = getattr(app.state, "aggregator", None)
        aclose = getattr(aggregator, "aclose", None)
        if aclose is not None:
            result = aclose()
            if inspect.isawaitable(result):
                await result
        if repository is not None:
            try:
                repository.close()
            except Exception:  # pragma: no cover - defensive
                logger.debug("Repository close failed", exc_info=True)


def create_app(*, aggregator: Aggregator | None = None) -> FastAPI:
    """Build and configure the FastAPI application.

    An existing *aggregator* can be injected (useful for tests or a custom
    scraper mix).  Otherwise one is created lazily on the first request.
    """

    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=DESCRIPTION,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        openapi_tags=TAGS_METADATA,
        debug=settings.debug,
        lifespan=_lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        # Reflecting "*" with credentials is unsafe; only enable credentials
        # for an explicit origin allow-list.
        allow_credentials="*" not in settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    prefix = f"{settings.api_prefix.rstrip('/')}/api/v1"
    app.include_router(products.router, prefix=prefix)
    app.include_router(images.router, prefix=prefix)
    app.include_router(stores.router, prefix=prefix)
    app.include_router(basket.router, prefix=prefix)
    app.include_router(history.router, prefix=prefix)
    app.include_router(crowd.router, prefix=prefix)
    # Export before the parameterised receipt routes so /receipts/export
    # is not captured as receipt_id="export".
    app.include_router(export_router.router, prefix=prefix)
    app.include_router(receipts_router.router, prefix=prefix)
    app.include_router(system.router, prefix=prefix)
    app.include_router(admin_db.router, prefix=prefix)

    # --- static frontend (PWA + Capacitor webDir) -----------------------
    frontend = _frontend_dir()
    for name in ("css", "js", "icons", "assets"):
        directory = frontend / name
        if directory.is_dir():
            app.mount(
                f"/{name}", StaticFiles(directory=str(directory)), name=f"static-{name}"
            )

    @app.get("/manifest.webmanifest", include_in_schema=False)
    async def manifest() -> Response:
        path = frontend / "manifest.webmanifest"
        if not path.is_file():
            return PlainTextResponse("not found", status_code=404)
        return FileResponse(
            path, media_type="application/manifest+json"
        )

    @app.get("/sw.js", include_in_schema=False)
    async def service_worker() -> Response:
        path = frontend / "sw.js"
        if not path.is_file():
            return PlainTextResponse("not found", status_code=404)
        return FileResponse(
            path,
            media_type="application/javascript",
            headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"},
        )

    app.state.aggregator = aggregator

    def _finite(value: object) -> object:
        """Replace NaN/Infinity so a 422 response stays serialisable."""

        if isinstance(value, float) and not math.isfinite(value):
            return str(value)
        if isinstance(value, dict):
            return {key: _finite(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [_finite(item) for item in value]
        return value

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Return 422 even when the invalid input contains NaN/Infinity."""

        return JSONResponse(
            status_code=422,
            content={"detail": _finite(jsonable_encoder(exc.errors()))},
        )

    RATE_LIMITED_PREFIXES = (prefix + "/", "/")
    STATIC_PREFIXES = (
        "/css/", "/js/", "/icons/", "/assets/",
        "/manifest.webmanifest", "/sw.js",
    )

    @app.middleware("http")
    async def stealth_and_gate(request: Request, call_next):  # type: ignore[no-untyped-def]
        """Rate limit + password gate + admin gate (fail-closed) + security headers."""

        current = get_settings()
        path = request.url.path

        # --- read rate limit (skip health/login/static) ------------------
        if (
            path.startswith(RATE_LIMITED_PREFIXES)
            and not path.startswith(STATIC_PREFIXES)
            and not is_public_path(path)
            and not allow_read(request)
        ):
                return JSONResponse(
                    {"detail": "Zu viele Anfragen – bitte kurz warten."},
                    status_code=429,
                    headers={"Retry-After": "60"},
                )

        # --- admin gate (fail-closed) ------------------------------------
        if is_admin_path(path):
            if not current.admin_password:
                return JSONResponse(
                    {
                        "detail": (
                            "Admin-Bereich ist deaktiviert "
                            "(ADMIN_PASSWORD nicht gesetzt)."
                        )
                    },
                    status_code=503,
                )
            if not is_admin_authenticated(request, current):
                return JSONResponse(
                    {"detail": "Nicht autorisiert."},
                    status_code=401,
                    headers={"WWW-Authenticate": 'Basic realm="Admin"'},
                )

        # --- site password gate (stealth mode) ----------------------------
        gated = bool(current.site_password) and not is_public_path(path)
        if gated and not is_authenticated(request, current):
            wants_html = "text/html" in (request.headers.get("accept") or "")
            if wants_html:
                target = "/login"
                if path not in {"/", ""}:
                    target += "?next=" + path
                return RedirectResponse(target, status_code=303)
            # No Basic challenge: browsers would open their own password dialog.
            return JSONResponse(
                {"detail": "Anmeldung erforderlich."},
                status_code=401,
            )

        response = await call_next(request)

        # --- security headers --------------------------------------------
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(self), microphone=(self), geolocation=()",
        )
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: https://images.openfoodfacts.org "
            "https://img.openfoodfacts.org https://static.openfoodfacts.org; "
            "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
            "connect-src 'self'",
        )

        if current.stealth_mode:
            response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        return response

    @app.get("/health", tags=["system"], summary="Health check")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": settings.app_version}

    @app.get("/robots.txt", include_in_schema=False)
    async def robots() -> PlainTextResponse:
        current = get_settings()
        if current.stealth_mode:
            body = "User-agent: *\nDisallow: /\n"
        else:
            body = "User-agent: *\nAllow: /\n"
        return PlainTextResponse(body)

    @app.get("/login", include_in_schema=False)
    async def login_page(next: str = "/", error: str = "") -> HTMLResponse:
        return HTMLResponse(
            content=_login_html(next_path=next, error=bool(error)),
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/login", include_in_schema=False)
    async def login_submit(
        password: str = Form(""),
        next: str = Form("/"),
    ) -> Response:
        current = get_settings()
        target = (
            next
            if next.startswith("/") and not next.startswith("//") and "\\" not in next
            else "/"
        )
        if not password_matches(current, password):
            return RedirectResponse("/login?error=1", status_code=303)
        response = RedirectResponse(target, status_code=303)
        set_session_cookie(response, current)
        return response

    @app.post("/logout", include_in_schema=False)
    async def logout() -> Response:
        response = RedirectResponse("/login", status_code=303)
        clear_session_cookie(response)
        return response

    @app.get("/admin", include_in_schema=False)
    async def admin_page() -> HTMLResponse:
        """Admin database dashboard (protected by the password gate)."""

        return HTMLResponse(
            content=load_admin_html(), headers={"Cache-Control": "no-store"}
        )

    @app.get("/", tags=["system"], include_in_schema=False)
    async def root() -> HTMLResponse:
        """Serve the FairBon app shell."""

        html = load_frontend_shell()
        current = get_settings()
        meta = (
            '<meta name="robots" content="noindex, nofollow">'
            if current.stealth_mode
            else ""
        )
        content = (
            html.replace("<!--SEO-ROBOTS-->", meta)
            if "<!--SEO-ROBOTS-->" in html
            else html
        )
        return HTMLResponse(
            content=content,
            headers={"Cache-Control": "no-cache"},
        )

    return app


app = create_app()

__all__ = ["app", "create_app", "get_aggregator"]
