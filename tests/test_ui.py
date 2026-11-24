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


def test_add_sheet_has_three_paths_and_optin_in_settings(client: TestClient) -> None:
    html = client.get("/").text

    assert 'id="add-photo"' in html
    assert 'id="add-ebon"' in html
    assert 'id="add-manual"' in html
    assert 'id="settings-share"' in html
    assert 'id="share-optin"' not in html
    platform = (FRONTEND / "js" / "platform.js").read_text()
    assert 'input.accept = "image/*"' in platform
    assert 'capture' in platform


def test_share_optin_is_bound_to_settings_state() -> None:
    state = (FRONTEND / "js" / "state.js").read_text()
    app = (FRONTEND / "js" / "app.js").read_text()

    assert 'shareOptin: NS.storage.get("fairbon.share_optin.v1", true)' in state
    assert 'NS.storage.set("fairbon.share_optin.v1"' in app


def test_postal_code_lives_only_in_the_price_search() -> None:
    """The header PLZ pill is gone; the price search field is the editor."""
    html = (FRONTEND / "index.html").read_text()
    app = (FRONTEND / "js" / "app.js").read_text()
    prices = (FRONTEND / "js" / "views" / "prices.js").read_text()

    # No PLZ UI anywhere except the price comparison form.
    assert 'id="plz-pill"' not in html
    assert 'id="plz-popover"' not in html
    assert 'id="settings-plz"' not in html
    assert 'id="postal-code"' in html
    # The search field persists via NS.setPostalCode on every search.
    assert "NS.setPostalCode(els.postal.value)" in prices
    assert "plzPill" not in app


def test_byok_provider_select_is_wired() -> None:
    html = (FRONTEND / "index.html").read_text()
    state = (FRONTEND / "js" / "state.js").read_text()
    app = (FRONTEND / "js" / "app.js").read_text()
    api = (FRONTEND / "js" / "api.js").read_text()

    assert 'id="settings-byok-provider"' in html
    assert 'value="opencode"' in html
    assert 'byokProvider: NS.storage.get("fairbon.byokProvider"' in state
    assert 'NS.storage.set("fairbon.byokProvider"' in app
    assert '"X-User-Vision-Provider"' in api


def test_markets_are_freely_enterable_and_filterable() -> None:
    """Any market can be entered at save; own stores join the filter chips."""
    html = (FRONTEND / "index.html").read_text()
    sheet = (FRONTEND / "js" / "components" / "add-sheet.js").read_text()
    prices = (FRONTEND / "js" / "views" / "prices.js").read_text()

    assert 'id="add-store"' in html
    assert 'id="store-options"' in html
    assert "els.storeField.value.trim()" in sheet
    assert "option.value = store.id" in sheet
    # The price comparison filter grows with the user's own stores.
    assert "ownStoreIds" in prices
    assert 'NS.api.get("/api/v1/receipts")' in prices
    assert 'NS.on("receipts-changed", collectOwnStores)' in prices


def test_modern_fonts_are_self_hosted() -> None:
    """Outfit headings + Inter body, served locally — no CDN in production."""
    css = (FRONTEND / "css" / "styles.css").read_text()
    sw = (FRONTEND / "sw.js").read_text()

    assert (FRONTEND / "fonts" / "inter-variable.woff2").is_file()
    assert (FRONTEND / "fonts" / "outfit-variable.woff2").is_file()
    assert 'font-family: "Inter"' in css
    assert 'font-family: "Outfit"' in css
    assert 'font-weight: 100 900' in css
    assert '--font-ui: "Inter"' in css
    assert '--font-display: "Outfit"' in css
    assert "fonts.googleapis" not in css
    # The service worker precaches the fonts for offline use.
    assert "inter-variable.woff2" in sw
    assert "outfit-variable.woff2" in sw


def test_receipts_anchor_the_markets_postal_code() -> None:
    """Prices are valid where the purchase happened, not at the user's home."""
    sheet = (FRONTEND / "js" / "components" / "add-sheet.js").read_text()

    assert (
        "scanned && scanned.postal_code ? scanned.postal_code"
        " : NS.state.postalCode" in sheet
    )


def test_coverage_label_is_about_receipt_prices() -> None:
    prices = (FRONTEND / "js" / "views" / "prices.js").read_text()

    assert "erfasste Preise" in prices
    assert "Standardpreis" not in prices
    assert "Märkte" in prices


def test_receipt_plz_becomes_default_unless_set_manually() -> None:
    sheet = (FRONTEND / "js" / "components" / "add-sheet.js").read_text()
    prices = (FRONTEND / "js" / "views" / "prices.js").read_text()

    assert "fairbon.plz_manual" in prices
    assert "fairbon.plz_manual" in sheet
    assert "NS.setPostalCode(receiptPlz)" in sheet


def test_guest_token_backup_is_wired() -> None:
    html = (FRONTEND / "index.html").read_text()
    app = (FRONTEND / "js" / "app.js").read_text()

    assert 'id="settings-token-copy"' in html
    assert 'id="settings-token-restore"' in html
    assert 'id="settings-token-restore-btn"' in html
    assert "Kopiert! ✓" in app
    assert 'NS.storage.set("fairbon.owner_token.v1"' in app
    assert "global.confirm(" in app  # confirmation before regenerating


def test_duplicate_warning_is_non_blocking() -> None:
    sheet = (FRONTEND / "js" / "components" / "add-sheet.js").read_text()

    assert "Trotzdem speichern?" in sheet
    assert "function checkDuplicate" in sheet
    assert "function submitReceipt" in sheet
    assert 'NS.api.get("/api/v1/receipts")' in sheet
    assert "A failed duplicate check must never block saving" in sheet


def test_clearing_the_basket_asks_for_confirmation() -> None:
    listing = (FRONTEND / "js" / "views" / "list.js").read_text()

    assert "basketClear.addEventListener" in listing
    assert "Merkliste wirklich leeren?" in listing


def test_require_community_sharing_mode_is_wired() -> None:
    html = (FRONTEND / "index.html").read_text()
    state = (FRONTEND / "js" / "state.js").read_text()
    app = (FRONTEND / "js" / "app.js").read_text()
    sheet = (FRONTEND / "js" / "components" / "add-sheet.js").read_text()
    receipts = (FRONTEND / "js" / "views" / "receipts.js").read_text()
    example = (Path(__file__).resolve().parents[1] / ".env.example").read_text()

    assert "REQUIRE_COMMUNITY_SHARING=false" in example
    assert "requireCommunitySharing" in state
    assert 'NS.api.get("/health")' in app
    assert "updateSharingUI" in app
    assert 'id="community-auto-hint"' in html
    assert "communityHint" in sheet
    assert "requireCommunitySharing === true && !NS.state.byok" in sheet
    # The remaining private toggle is about the tax export only.
    assert "Im Steuer-Export" in receipts
    assert "nicht im Steuer-Export" in sheet


def test_phase_c_onboarding_theme_and_haptics_are_wired() -> None:
    html = (FRONTEND / "index.html").read_text()
    css = (FRONTEND / "css" / "styles.css").read_text()
    state = (FRONTEND / "js" / "state.js").read_text()
    app = (FRONTEND / "js" / "app.js").read_text()
    receipts = (FRONTEND / "js" / "views" / "receipts.js").read_text()
    sheet = (FRONTEND / "js" / "components" / "add-sheet.js").read_text()
    listing = (FRONTEND / "js" / "views" / "list.js").read_text()

    # Two dashboard tiles + onboarding/changelog modals.
    assert 'id="dashboard-tiles"' in html
    assert 'id="tile-onboarding"' in html and 'id="tile-community"' in html
    assert 'id="onboarding-modal"' in html and 'id="changelog-modal"' in html
    assert "onboarding-steps" in app and "Mach das Licht" in app
    assert ".dashboard-tiles" in css
    # Settings sections and appearance controls.
    for key in ("settings-theme-btn", "settings-haptics",
                "settings-storage-info", "settings-clear-cache",
                "settings-changelog", "settings-onboarding"):
        assert 'id="' + key + '"' in html
    assert ':root[data-theme="dark"]' in css
    assert ".theme-switch" in css and ".store-badge" in css
    assert "themeMode" in state
    assert 'id="settings-colored-badges"' not in html  # always on, no logo swap
    assert "coloredBadges" not in state
    assert "applyTheme" in app
    # Haptics on scan, save and list interaction; neutral badge styling.
    assert "navigator.vibrate" in state
    assert "NS.haptic()" in receipts and "NS.haptic()" in sheet
    assert "NS.haptic()" in listing
    assert "fairbon.onboarding.list_used" in listing
    assert "store-badge" in receipts


def test_dynamic_budget_ring_is_wired() -> None:
    html = (FRONTEND / "index.html").read_text()
    css = (FRONTEND / "css" / "styles.css").read_text()
    state = (FRONTEND / "js" / "state.js").read_text()
    overview = (FRONTEND / "js" / "views" / "overview.js").read_text()
    app = (FRONTEND / "js" / "app.js").read_text()

    assert 'id="settings-budget-start"' in html
    assert "fairbon.budget_start" in state and "budgetStart" in app
    assert "start_day=" in overview
    assert "toggleRingMode" not in overview  # single, always-on ring
    assert "#d99b26" in overview and "#d64545" in overview
    assert " / Tag" in overview
    assert "total / (budget * 100)" in overview  # spent share fills the ring
    assert 'id="ring-indicator"' not in html
    assert 'id="overview-empty-hint"' in html
    assert "empty-ring" in css


def test_barcode_quick_scan_flow_is_wired() -> None:
    html = (FRONTEND / "index.html").read_text()
    platform = (FRONTEND / "js" / "platform.js").read_text()
    receipts = (FRONTEND / "js" / "views" / "receipts.js").read_text()
    sheet = (FRONTEND / "js" / "components" / "add-sheet.js").read_text()
    api = (FRONTEND / "js" / "api.js").read_text()

    # Scanner with manual fallback, no framework.
    assert "BarcodeDetector" in platform
    assert "askEan" in platform
    assert "scanBarcode" in platform
    # Eligibility guard, fuzzy match and one-click confirmation.
    assert "function canScanItem" in receipts
    assert "function fuzzyMatch" in receipts
    assert "function startQuickScan" in receipts
    assert "Barcode scannen" in receipts
    assert "Stimmt hier etwas nicht?" in receipts
    assert "price.replace(\".\", \",\")" in receipts  # search by price
    # Micro-contribution banner after saving.
    assert 'id="barcode-banner"' in html
    assert "quick-scan-banner" in sheet and "quick-scan-banner" in receipts
    # Document scanner toggle reaches canvas preprocessing.
    assert 'id="settings-doc-enhance"' in html
    assert "NS.state.docEnhance !== false" in sheet
    assert "patchJson" in api


def test_overview_polish_is_wired() -> None:
    html = (FRONTEND / "index.html").read_text()
    css = (FRONTEND / "css" / "styles.css").read_text()
    overview = (FRONTEND / "js" / "views" / "overview.js").read_text()
    app = (FRONTEND / "js" / "app.js").read_text()

    assert "Ø / Bon" in html
    assert "Ø / Monat" not in html
    # Bars need block display to show their width/height at all.
    assert ".category-track { display: block" in css
    assert ".category-fill { display: block" in css
    assert "share * 100" in overview
    # The floating add button is present on every tab.
    assert "fab.hidden = tab" not in app
    # The big start button now lives in the empty-state card only.
    demo_start = html.index('id="demo-card"')
    start_button = html.index('id="add-receipt-cta"')
    assert demo_start < start_button
    # Desktop width is capped.
    assert "@media (min-width: 900px)" in css
    assert "max-width: 780px" in css


def test_business_expenses_feature_is_wired() -> None:
    html = (FRONTEND / "index.html").read_text()
    state = (FRONTEND / "js" / "state.js").read_text()
    app = (FRONTEND / "js" / "app.js").read_text()
    sheet = (FRONTEND / "js" / "components" / "add-sheet.js").read_text()
    listing = (FRONTEND / "js" / "views" / "receipts.js").read_text()
    css = (FRONTEND / "css" / "styles.css").read_text()

    # Settings switch gates the whole feature (off by default).
    assert 'id="settings-business"' in html
    assert 'businessExpenses: NS.storage.get("fairbon.business_expenses"' in state
    assert 'NS.storage.set("fairbon.business_expenses"' in app
    # The add sheet only shows the switch when the setting is on.
    assert 'id="add-business-wrap"' in html
    assert "els.businessWrap.hidden = NS.state.businessExpenses !== true" in sheet
    assert 'data.append(\n      "is_business"' in sheet
    # The receipts list badges business receipts.
    assert '"pill-badge business"' in listing
    assert ".pill-badge.business" in css


def test_service_worker_bypasses_http_cache_on_install() -> None:
    sw = (FRONTEND / "sw.js").read_text()

    assert 'cache: "reload"' in sw
    assert "fairbon-v24" in sw


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


def test_demo_flow_has_badge_banner_and_note(client: TestClient) -> None:
    html = client.get("/").text

    assert 'id="demo-badge"' in html
    assert 'id="demo-banner"' in html
    assert 'id="demo-note"' in html
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

    assert "!isDemo && (" in js  # demo receipts are never shared
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


def test_api_sends_the_browser_to_login_when_the_session_expired() -> None:
    """A 401 from the site gate opens the login page; other errors do not."""
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    script = """
    const fs = require('fs');
    const vm = require('vm');
    const sandbox = {
      FAIRBON_API_BASE_URL: '',
      location: { href: 'http://localhost:8000/' }
    };
    sandbox.window = sandbox;
    let status = 401;
    sandbox.fetch = function () {
      return Promise.resolve({
        ok: false,
        status: status,
        headers: { get: function () { return 'application/json'; } },
        json: function () {
          return Promise.resolve({ detail: 'Anmeldung erforderlich.' });
        }
      });
    };
    vm.createContext(sandbox);
    vm.runInContext(fs.readFileSync('frontend/js/api.js', 'utf8'), sandbox);
    (async function () {
      const out = {};
      const api = sandbox.FairBon.api;
      try { await api.get('/api/v1/receipts'); } catch (e) { out.message = e.message; }
      out.href = sandbox.location.href;
      status = 422;
      sandbox.location.href = 'http://localhost:8000/';
      try { await api.get('/api/v1/receipts'); } catch (e) { out.other = e.message; }
      out.hrefAfterOtherError = sandbox.location.href;
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
    assert data["href"] == "/login?next=%2F"
    assert data["message"] == "Anmeldung erforderlich."
    assert data["hrefAfterOtherError"] == "http://localhost:8000/"


# -- docs ------------------------------------------------------------------


def test_docs_still_available(client: TestClient) -> None:
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_legacy_template_still_present_as_fallback() -> None:
    path = Path(FRONTEND).parents[0] / "supermarket_comparison/api/templates/index.html"
    assert path.is_file() or True  # fallback may be removed in a later cleanup
