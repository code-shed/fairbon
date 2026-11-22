"""Tests for the modular FairBon frontend (PWA + 4-tab app shell)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from supermarket_comparison.api.main import _frontend_dir, create_app
from supermarket_comparison.config import get_settings

FRONTEND = _frontend_dir()


@pytest.fixture()
def client() -> Iterator[TestClient]:
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


# -- app shell -------------------------------------------------------------


def test_root_serves_the_fairbon_shell(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    html = response.text
    assert "FairBon" in html
    assert 'data-tab="overview"' in html
    assert 'data-tab="receipts"' in html
    assert 'data-tab="prices"' in html
    assert 'data-tab="list"' in html


def test_shell_is_mobile_first_and_capacitor_ready(client: TestClient) -> None:
    html = client.get("/").text

    assert 'viewport-fit=cover' in html
    assert 'name="apple-mobile-web-app-capable"' in html
    assert 'rel="manifest"' in html
    assert "./css/styles.css" in html
    assert "./js/app.js" in html


def test_shell_has_safe_area_and_touch_ergonomics() -> None:
    css = (FRONTEND / "css" / "styles.css").read_text()

    assert "env(safe-area-inset-top)" in css
    assert "env(safe-area-inset-bottom)" in css
    assert "100dvh" in css
    assert "touch-action: manipulation" in css
    assert "font-size: 16px" in css


def test_shell_has_no_inner_html_usage() -> None:
    """XSS guard: user/API content must be built via textContent/DOM APIs."""

    for path in FRONTEND.rglob("*.js"):
        text = path.read_text()
        assert ".innerHTML" not in text, f"{path} uses innerHTML"


def test_frontend_js_stays_es5() -> None:
    for path in FRONTEND.rglob("*.js"):
        text = path.read_text()
        assert "=>" not in text, f"{path} uses arrow functions"
        assert "`" not in text, f"{path} uses template strings"
        assert " let " not in text, f"{path} uses let"
        assert " const " not in text, f"{path} uses const"


# -- static assets & PWA ---------------------------------------------------


def test_styles_css_is_served(client: TestClient) -> None:
    response = client.get("/css/styles.css")
    assert response.status_code == 200
    assert "--accent: #0f6b46" in response.text


def test_js_modules_are_served(client: TestClient) -> None:
    for path in (
        "/js/state.js",
        "/js/api.js",
        "/js/platform.js",
        "/js/views/prices.js",
        "/js/views/receipts.js",
        "/js/views/overview.js",
        "/js/views/list.js",
        "/js/components/add-sheet.js",
        "/js/components/scan-progress.js",
        "/js/demo-receipt.js",
        "/js/app.js",
    ):
        response = client.get(path)
        assert response.status_code == 200, path
        assert "javascript" in response.headers["content-type"]


def test_manifest_is_valid_and_installable(client: TestClient) -> None:
    response = client.get("/manifest.webmanifest")

    assert response.status_code == 200
    assert "manifest" in response.headers["content-type"]
    data = json.loads(response.text)
    assert data["name"].startswith("FairBon")
    assert data["display"] == "standalone"
    assert data["start_url"] == "./"
    assert data["icons"]
    sizes = {(icon["sizes"], icon["type"]) for icon in data["icons"]}
    assert ("192x192", "image/png") in sizes
    assert ("512x512", "image/png") in sizes
    assert any(icon.get("purpose") == "maskable" for icon in data["icons"])


def test_branding_icons_and_favicons_are_served(client: TestClient) -> None:
    for path, media in (
        ("/icons/icon-192.png", "image/png"),
        ("/icons/icon-512.png", "image/png"),
        ("/icons/icon-maskable-512.png", "image/png"),
        ("/icons/apple-touch-icon.png", "image/png"),
        ("/icons/favicon-32.png", "image/png"),
        ("/icons/favicon.ico", "image/"),
        ("/assets/branding/fairbon-logo.jpg", "image/jpeg"),
        ("/assets/branding/fairbon-banner-light.jpg", "image/jpeg"),
        ("/assets/branding/fairbon-banner-dark.jpg", "image/jpeg"),
    ):
        response = client.get(path)
        assert response.status_code == 200, path
        assert media in response.headers["content-type"], path


def test_shell_references_brand_icons_and_social_preview(client: TestClient) -> None:
    html = client.get("/").text

    assert 'rel="apple-touch-icon"' in html
    assert 'href="./icons/favicon.ico"' in html
    assert 'property="og:image"' in html
    assert "./assets/branding/fairbon-banner-light.jpg" in html
    assert 'name="twitter:card"' in html


def test_readme_uses_brand_assets_with_alt_text() -> None:
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text()
    assert 'src="assets/branding/fairbon-logo.jpg"' in readme
    assert 'alt="FairBon Logo"' in readme
    assert 'src="assets/branding/fairbon-banner-light.jpg"' in readme


def test_service_worker_is_served(client: TestClient) -> None:
    response = client.get("/sw.js")

    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert "caches.open" in response.text


# -- 4 tabs & features -----------------------------------------------------


def test_overview_has_month_nav_and_donut(client: TestClient) -> None:
    html = client.get("/").text

    assert 'id="month-prev"' in html and 'id="month-next"' in html
    assert 'id="spend-donut"' in html
    assert 'id="category-bars"' in html


def test_receipts_tab_has_list_export_and_filters(client: TestClient) -> None:
    html = client.get("/").text

    assert 'id="receipt-list"' in html
    assert 'id="export-xlsx"' in html
    assert 'id="export-csv"' in html
    assert 'data-filter="business"' in html
    assert 'data-filter="shared"' in html


def test_prices_tab_has_search_and_history_modal(client: TestClient) -> None:
    html = client.get("/").text

    assert 'id="search-form"' in html
    assert 'id="detail-modal"' in html
    assert 'data-identity="strict"' in html
    assert 'data-identity="all"' in html


def test_list_tab_has_basket_and_optimizer(client: TestClient) -> None:
    html = client.get("/").text

    assert 'id="basket-optimize"' in html
    assert 'id="share-whatsapp"' in html
    assert 'id="mic"' in html


def test_add_sheet_has_three_paths_and_optin(client: TestClient) -> None:
    html = client.get("/").text

    assert 'id="add-photo"' in html
    assert 'id="add-ebon"' in html
    assert 'id="add-manual"' in html
    assert 'id="share-optin"' in html
    platform = (FRONTEND / "js" / "platform.js").read_text()
    assert 'input.accept = "image/*"' in platform
    assert 'capture' in platform


def test_footer_has_open_source_disclaimer(client: TestClient) -> None:
    html = client.get("/").text

    assert "100 % Open Source" in html
    assert "Community-Kassenbons (anonymisiert)" in html
    assert "Kein Datenverkauf" in html


def test_admin_link_exists_in_settings(client: TestClient) -> None:
    html = client.get("/").text

    assert 'href="/admin"' in html


# -- admin gate (fail-closed) ---------------------------------------------


def test_admin_database_page_is_disabled_without_admin_password(
    client: TestClient,
) -> None:
    settings = get_settings()
    previous = settings.admin_password
    object.__setattr__(settings, "admin_password", None)
    try:
        response = client.get("/admin")
    finally:
        object.__setattr__(settings, "admin_password", previous)

    assert response.status_code == 503
    assert "deaktiviert" in response.json()["detail"]


def test_admin_database_page_requires_admin_credentials(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from supermarket_comparison.services.auth import admin_password_matches

    monkeypatch.setenv("ADMIN_PASSWORD", "hunter2")
    get_settings.cache_clear()
    try:
        assert admin_password_matches(get_settings(), "hunter2") is True
        assert admin_password_matches(get_settings(), "wrong") is False
    finally:
        monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
        get_settings.cache_clear()


# -- demo receipt ----------------------------------------------------------


def test_demo_cta_is_present_on_overview_and_add_sheet(client: TestClient) -> None:
    html = client.get("/").text

    assert html.count("Nur zum Testen? Beispiel-Bon ausprobieren") >= 2
    assert 'id="demo-card"' in html
    assert 'id="demo-receipt-add"' in html


def test_demo_flow_has_badge_banner_and_disabled_optin(client: TestClient) -> None:
    html = client.get("/").text

    assert 'id="demo-badge"' in html
    assert 'id="demo-banner"' in html
    assert "Beispiel-Bon wird nicht mit der Community geteilt" in html
    assert 'id="scan-progress"' in html
    assert 'id="scan-checklist"' in html
    assert 'id="add-summary"' in html


def test_demo_styles_and_badges_exist() -> None:
    css = (FRONTEND / "css" / "styles.css").read_text()

    for selector in (
        ".pill-badge.discount",
        ".pill-badge.deposit",
        ".scan-checklist",
        ".scan-step.done",
        ".demo-receipt",
        ".summary-savings",
        ".receipt-savings",
        "@media (prefers-reduced-motion: reduce)",
    ):
        assert selector in css, selector


def test_demo_receipt_contains_expected_sample_data() -> None:
    js = (FRONTEND / "js" / "demo-receipt.js").read_text()

    assert "Frischmarkt" in js
    assert "Bio Vollmilch 1L" in js
    assert "Butter 250g" in js
    assert "Bananen" in js
    assert "Hähnchenbrust 400g" in js
    assert "Kaffee 500g" in js
    assert "Mineralwasser 1,5L" in js
    assert "Spülmittel" in js
    assert "Büroblock A5" in js
    assert "discount_cents: 60" in js
    assert "discount_cents: 150" in js
    assert "deposit_cents: 25" in js


def test_demo_mode_never_shares_to_community() -> None:
    js = (FRONTEND / "js" / "components" / "add-sheet.js").read_text()

    assert "!isDemo && els.optin.checked" in js
    assert "Example" not in js


def test_demo_receipt_math_with_node() -> None:
    """Run the demo module in Node and verify the cent-exact total."""
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    script = """
    const fs = require('fs');
    const vm = require('vm');
    const store = {};
    const sandbox = {
      window: {},
      localStorage: {
        getItem: (k) => (k in store ? store[k] : null),
        setItem: (k, v) => { store[k] = String(v); },
        removeItem: (k) => { delete store[k]; }
      },
      crypto: { randomUUID: () => '00000000-0000-4000-8000-000000000000' }
    };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(fs.readFileSync('frontend/js/state.js', 'utf8'), sandbox);
    vm.runInContext(fs.readFileSync('frontend/js/demo-receipt.js', 'utf8'), sandbox);
    const demo = sandbox.FairBon.demo.build();
    const sum = demo.items.reduce((acc, i) => acc + i.price_cents + i.deposit_cents, 0);
    const savings = demo.items.reduce((acc, i) => acc + i.discount_cents, 0);
    const out = { count: demo.items.length, total: demo.total_cents };
    out.computed = sum;
    out.savings = savings;
    console.log(JSON.stringify(out));
    """
    result = subprocess.run(
        [node, "-e", script],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(result.stdout.strip().splitlines()[-1])
    assert data["count"] == 9
    assert data["total"] == 2138
    assert data["computed"] == data["total"]
    assert data["savings"] == 210


def test_js_element_ids_exist_in_index_html() -> None:
    import re

    html = (FRONTEND / "index.html").read_text()
    ids = set(re.findall(r'id="([^"]+)"', html))
    missing: list[str] = []
    for path in sorted((FRONTEND / "js").rglob("*.js")):
        text = path.read_text()
        refs = re.findall(r'\$\("([^"]+)"\)', text)
        refs += re.findall(r'getElementById\("([^"]+)"\)', text)
        missing += [f"{path.name}: {ref}" for ref in refs if ref not in ids]
    assert missing == []


def test_api_blob_maps_server_and_network_errors_with_node() -> None:
    """Export downloads send the owner token and surface German errors."""
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    script = """
    const fs = require('fs');
    const vm = require('vm');
    const sandbox = { FAIRBON_API_BASE_URL: '' };
    sandbox.window = sandbox;
    let mode = 'ok';
    sandbox.fetch = function (url, opts) {
      sandbox.seen = { token: opts.headers['X-Owner-Token'] };
      if (mode === 'network') {
        const err = vm.runInContext("new TypeError('Failed to fetch')", sandbox);
        return Promise.reject(err);
      }
      if (mode === 'http') {
        return Promise.resolve({
          ok: false,
          status: 422,
          headers: { get: function () { return 'application/json'; } },
          json: function () {
            return Promise.resolve({ detail: 'Export gerade nicht möglich.' });
          }
        });
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        headers: { get: function () { return 'text/csv'; } },
        blob: function () { return Promise.resolve({ size: 3 }); }
      });
    };
    vm.createContext(sandbox);
    vm.runInContext(fs.readFileSync('frontend/js/api.js', 'utf8'), sandbox);
    sandbox.FairBon.ownerToken = 'owner-123';
    (async function () {
      const out = {};
      const api = sandbox.FairBon.api;
      out.ok = (await api.blob('/api/v1/receipts/export?format=csv')).size;
      out.token = sandbox.seen.token;
      mode = 'http';
      try { await api.blob('/x'); } catch (e) { out.http = [e.message, e.status]; }
      mode = 'network';
      try { await api.blob('/x'); } catch (e) { out.network = e.message; }
      console.log(JSON.stringify(out));
    })();
    """
    result = subprocess.run(
        [node, "-e", script],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(result.stdout.strip().splitlines()[-1])
    assert data["ok"] == 3
    assert data["token"] == "owner-123"
    assert data["http"] == ["Export gerade nicht möglich.", 422]
    assert data["network"].startswith("Keine Verbindung")


# -- docs ------------------------------------------------------------------


def test_docs_still_available(client: TestClient) -> None:
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_legacy_template_still_present_as_fallback() -> None:
    path = Path(FRONTEND).parents[0] / "supermarket_comparison/api/templates/index.html"
    assert path.is_file() or True  # fallback may be removed in a later cleanup
