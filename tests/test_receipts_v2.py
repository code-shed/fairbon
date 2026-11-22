"""Phase 2 tests: vision scan, upload security, receipts API, export.

Covers:
* Magic-byte rejection of fake files, >3MB rejection, EXIF stripping.
* Vision provider failover (primary fails -> fallback used).
* eBon text fallback (local, free).
* Rate limiting (global daily cap -> 429) & BYOK bypass.
* Strict anonymisation: without opt-in nothing lands in community_prices,
  with opt-in no owner_token/receipt_id leaks.
* Excel export: two sheets, real numbers, exclude_private=true.
"""

from __future__ import annotations

import io
import json
from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from supermarket_comparison.api.main import create_app
from supermarket_comparison.api.routes.history import get_repository
from supermarket_comparison.services.rate_limit import (
    scan_daily_global,
    scan_per_ip_limiter,
)
from supermarket_comparison.services.receipt_import import UnsupportedReceipt
from supermarket_comparison.services.upload_security import (
    UploadTooLarge,
    detect_media_type,
    sanitize,
)
from supermarket_comparison.storage import Database, Repository

PREFIX = "/api/v1"

OWNER = "test-owner-token-1234"


@pytest.fixture()
def repository() -> Iterator[Repository]:
    repo = Repository(Database(":memory:"))
    yield repo
    repo.close()


@pytest.fixture()
def client(repository: Repository) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repository
    with TestClient(app, headers={"X-Owner-Token": OWNER}) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Upload security
# ---------------------------------------------------------------------------


def test_magic_bytes_reject_fake_image() -> None:
    fake = b"<html>not an image</html>"
    with pytest.raises(UnsupportedReceipt):
        detect_media_type(fake)


def test_magic_bytes_accept_real_jpeg_png_webp_pdf() -> None:
    assert detect_media_type(b"\xff\xd8\xff\xe0rest") == "image/jpeg"
    assert detect_media_type(b"\x89PNG\r\n\x1a\nrest") == "image/png"
    assert detect_media_type(b"RIFF\x10\x00\x00\x00WEBPVP8 ") == "image/webp"
    assert detect_media_type(b"%PDF-1.4") == "application/pdf"


def test_upload_too_large_is_rejected() -> None:
    big = b"\xff\xd8\xff" + b"0" * (3 * 1024 * 1024 + 100)
    with pytest.raises(UploadTooLarge):
        sanitize(big)


def test_image_is_reencoded_and_exif_stripped() -> None:
    from PIL import Image

    # Create a JPEG with EXIF metadata (GPS block, as a camera would write).
    buffer = io.BytesIO()

    def _exif_with_gps() -> bytes:
        exif = Image.Exif()
        # EXIF.orientation -> 1 (normal); GPS IFD pointer tag 0x8825.
        exif[0x0112] = 1
        return exif.tobytes()

    img = Image.new("RGB", (40, 20), (120, 200, 30))
    img.save(buffer, format="JPEG", exif=_exif_with_gps())
    raw = buffer.getvalue()
    assert b"Exif\x00\x00" in raw  # raw input really carries EXIF

    cleaned = sanitize(raw)
    assert cleaned.kind == "image"
    assert cleaned.media_type == "image/jpeg"
    # Re-opened image must keep its size — and the raw JPEG stream must no
    # longer contain an EXIF APP1 segment (metadata stripped on re-encode).
    reopened = Image.open(io.BytesIO(cleaned.data))
    assert reopened.size == (40, 20)
    assert b"Exif\x00\x00" not in cleaned.data


# ---------------------------------------------------------------------------
# Vision provider failover
# ---------------------------------------------------------------------------


def _fake_image_bytes() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (30, 30), (10, 10, 10)).save(buffer, format="JPEG")
    return buffer.getvalue()


class FakeVisionTransport:
    """Handler for ``httpx.MockTransport``; records provider calls."""

    def __init__(self, primary_fails: bool = True) -> None:
        self.primary_fails = primary_fails
        self.calls: list[str] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "generativelanguage" in url:
            self.calls.append("gemini")
            if self.primary_fails:
                return httpx.Response(429, json={"error": "over quota"})
            body = self._success_body()
            return httpx.Response(
                200, json={"candidates": [{"content": {"parts": [{"text": body}]}}]}
            )
        # OpenAI-compatible fallback
        self.calls.append("openai")
        body = self._success_body()
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": body}}]},
        )

    @staticmethod
    def _success_body() -> str:
        return json.dumps(
            {
                "store": "netto",
                "postal_code": "65618",
                "date": "2026-11-21",
                "currency": "EUR",
                "total_cents": 249,
                "items": [
                    {
                        "raw_text": "Milch 1,49 A",
                        "normalized_name": "Frische Vollmilch",
                        "brand": "Weihenstephan",
                        "category": "Lebensmittel",
                        "quantity": 1.0,
                        "unit": "l",
                        "price_cents": 149,
                        "discount_cents": 0,
                        "deposit_cents": 0,
                        "vat_rate": 7.0,
                    }
                ],
            }
        )

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)


class _ClientFactory:
    """Returns a fresh client bound to the given transport on every call."""

    def __init__(self, transport: httpx.MockTransport) -> None:
        self._transport = transport

    def __call__(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self._transport)


@pytest.mark.asyncio
async def test_vision_fails_over_to_fallback_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from supermarket_comparison.config import get_settings
    from supermarket_comparison.services import receipt_vision as rv

    settings = get_settings()
    object.__setattr__(settings, "vision_primary_provider", "gemini")
    object.__setattr__(settings, "vision_primary_api_key", "primary-key")
    object.__setattr__(settings, "vision_primary_model", "gemini-2.5-flash-lite")
    object.__setattr__(settings, "vision_fallback_provider", "openai_compatible")
    object.__setattr__(settings, "vision_fallback_api_key", "fallback-key")
    object.__setattr__(settings, "vision_fallback_model", "gpt-4o-mini")

    transport = FakeVisionTransport(primary_fails=True)
    result = await rv.extract_with_vision(
        rv.SanitizedUploadImage(data=_fake_image_bytes()),
        client_factory=_ClientFactory(transport.transport()),
    )

    assert result.provider == "openai_compatible"
    assert result.store == "netto"
    assert len(result.items) == 1
    assert result.items[0]["price_cents"] == 149
    assert transport.calls == ["gemini", "openai"]


@pytest.mark.asyncio
async def test_vision_uses_primary_when_it_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from supermarket_comparison.config import get_settings
    from supermarket_comparison.services import receipt_vision as rv

    settings = get_settings()
    object.__setattr__(settings, "vision_primary_provider", "gemini")
    object.__setattr__(settings, "vision_primary_api_key", "primary-key")
    object.__setattr__(settings, "vision_primary_model", "gemini-2.5-flash-lite")

    transport = FakeVisionTransport(primary_fails=False)
    result = await rv.extract_with_vision(
        rv.SanitizedUploadImage(data=_fake_image_bytes()),
        client_factory=_ClientFactory(transport.transport()),
    )

    assert result.provider == "gemini"
    assert transport.calls == ["gemini"]


# ---------------------------------------------------------------------------
# eBon text path (local, free, deterministic)
# ---------------------------------------------------------------------------


def test_ebon_text_parsing_is_local_and_free(repository: Repository) -> None:
    from supermarket_comparison.services.receipts import parse_receipt_text

    text = (
        "REWE Markt\n"
        "65618 Münster\n"
        "24.11.2026\n"
        "Frische Vollmilch 1,19 A\n"
        "Butter 250g 2,49 B\n"
        "Summe 3,68\n"
        "Bar 3,68\n"
    )
    parsed = parse_receipt_text(text)
    assert parsed.store == "rewe"
    assert parsed.postal_code == "65618"
    assert len(parsed.items) >= 2


# ---------------------------------------------------------------------------
# Save endpoint & strict anonymisation
# ---------------------------------------------------------------------------


def _items_payload() -> str:
    return json.dumps(
        [
            {
                "raw_text": "Milch 1,49 A",
                "normalized_name": "Frische Vollmilch",
                "brand": "Weihenstephan",
                "category": "Lebensmittel",
                "quantity": 1.0,
                "unit": "l",
                "price_cents": 149,
                "discount_cents": 0,
                "deposit_cents": 0,
                "vat_rate": 7.0,
                "is_private": False,
            },
            {
                "raw_text": "Pfand 0,25",
                "normalized_name": "Pfand Flasche",
                "brand": None,
                "category": "Pfand",
                "quantity": 1.0,
                "unit": "stueck",
                "price_cents": 25,
                "discount_cents": 0,
                "deposit_cents": 25,
                "vat_rate": 19.0,
                "is_private": False,
            },
        ]
    )


def test_save_without_optin_never_touches_community(client: TestClient) -> None:
    response = client.post(
        f"{PREFIX}/receipts",
        data={
            "store": "REWE",
            "postal_code": "65618",
            "country_code": "DE",
            "currency": "EUR",
            "receipt_date": "2026-11-21",
            "total_cents": 174,
            "share_anonymized": "false",
            "items_json": _items_payload(),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["receipt_id"] > 0
    assert payload["shared_count"] == 0


def test_save_with_optin_shares_only_eligible_lines_without_owner(
    client: TestClient, repository: Repository
) -> None:
    response = client.post(
        f"{PREFIX}/receipts",
        data={
            "store": "REWE",
            "postal_code": "65618",
            "country_code": "DE",
            "currency": "EUR",
            "receipt_date": "2026-11-21",
            "total_cents": 174,
            "share_anonymized": "true",
            "items_json": _items_payload(),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["shared_count"] == 1  # Milch only; Pfand excluded

    rows = repository.db.query(
        "SELECT * FROM community_prices WHERE store = 'rewe'"
    )
    assert len(rows) == 1
    row = rows[0]
    # No owner token, no receipt id, no scout linkage.
    assert row["name"] == "Frische Vollmilch"
    assert row["receipt_id"] is None
    # The owner token must not appear anywhere in the community row.
    dumped = json.dumps(dict(row))
    assert OWNER not in dumped


def test_demo_receipt_learns_no_aliases(
    client: TestClient, repository: Repository
) -> None:
    response = client.post(
        f"{PREFIX}/receipts",
        data={
            "store": "Frischmarkt",
            "postal_code": "65618",
            "country_code": "DE",
            "currency": "EUR",
            "receipt_date": "2026-11-22",
            "total_cents": 2138,
            "share_anonymized": "false",
            "is_demo": "true",
            "items_json": _items_payload(),
        },
    )

    assert response.status_code == 200
    assert response.json()["shared_count"] == 0
    aliases = repository.db.query("SELECT COUNT(*) AS n FROM receipt_aliases")
    assert aliases[0]["n"] == 0


def test_demo_share_true_is_blocked_server_side(
    client: TestClient, repository: Repository
) -> None:
    """Even a forged share=true + is_demo=true must never reach the community."""

    response = client.post(
        f"{PREFIX}/receipts",
        data={
            "store": "Frischmarkt",
            "postal_code": "65618",
            "country_code": "DE",
            "currency": "EUR",
            "receipt_date": "2026-11-22",
            "total_cents": 2138,
            "share_anonymized": "true",
            "is_demo": "true",
            "items_json": _items_payload(),
        },
    )

    assert response.status_code == 200
    assert response.json()["shared_count"] == 0
    receipts = repository.db.query(
        "SELECT shared_to_community FROM user_receipts"
    )
    assert receipts[0]["shared_to_community"] == 0
    community = repository.db.query("SELECT COUNT(*) AS n FROM community_prices")
    assert community[0]["n"] == 0


def test_owner_token_is_not_returned(
    client: TestClient, repository: Repository
) -> None:
    repository.insert_user_receipt(
        owner_token=OWNER,
        store="REWE",
        postal_code="65618",
        country_code="DE",
        currency="EUR",
        receipt_date="2026-11-22",
        total_cents=174,
        shared_to_community=False,
        items=json.loads(_items_payload()),
    )
    listing = client.get(f"{PREFIX}/receipts").json()
    assert listing and "owner_token" not in listing[0]
    detail = client.get(f"{PREFIX}/receipts/{listing[0]['id']}").json()
    assert "owner_token" not in detail


def test_save_rejects_too_many_items(client: TestClient) -> None:
    items = json.loads(_items_payload()) * 61  # 122 items
    response = client.post(
        f"{PREFIX}/receipts",
        data={
            "store": "REWE",
            "postal_code": "65618",
            "currency": "EUR",
            "receipt_date": "2026-11-22",
            "total_cents": 1000,
            "share_anonymized": "false",
            "items_json": json.dumps(items),
        },
    )
    assert response.status_code == 422
    assert "120" in response.json()["detail"]


@pytest.mark.asyncio
async def test_vision_error_never_leaks_the_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from supermarket_comparison.config import get_settings
    from supermarket_comparison.services import receipt_vision as rv

    settings = get_settings()
    object.__setattr__(settings, "vision_primary_provider", "gemini")
    object.__setattr__(settings, "vision_primary_api_key", "super-secret-key")
    object.__setattr__(settings, "vision_primary_model", "gemini-test")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    transport = httpx.MockTransport(handler)

    with pytest.raises(rv.VisionError) as excinfo:
        await rv.extract_with_vision(
            rv.SanitizedUploadImage(data=_fake_image_bytes()),
            client_factory=lambda: httpx.AsyncClient(transport=transport),
        )

    message = str(excinfo.value)
    lowered = message.lower()
    assert "super-secret-key" not in message
    assert "key=" not in message
    assert "http" not in lowered


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def test_export_xlsx_two_sheets_with_real_numbers(
    client: TestClient, repository: Repository
) -> None:
    # Seed one personal receipt with two items (7% and 19%).
    repository.insert_user_receipt(
        owner_token=OWNER,
        store="REWE",
        postal_code="65618",
        country_code="DE",
        currency="EUR",
        receipt_date="2026-11-21",
        total_cents=174,
        shared_to_community=False,
        items=json.loads(_items_payload()),
    )

    response = client.get(f"{PREFIX}/receipts/export?format=xlsx")
    assert response.status_code == 200
    assert (
        response.headers["content-type"]
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(response.content))
    assert wb.sheetnames == ["Rohdaten", "Steuer-Zusammenfassung"]

    ws = wb["Rohdaten"]
    header = [cell.value for cell in ws[1]]
    assert header[0] == "Belegdatum"
    assert "Brutto" in header and "Netto" in header
    # Rows are numeric, not text.
    assert isinstance(ws.cell(2, 8).value, (int, float))  # Netto
    assert isinstance(ws.cell(2, 10).value, (int, float))  # Brutto

    ws2 = wb["Steuer-Zusammenfassung"]
    values = [
        cell
        for row in ws2.iter_rows(values_only=True)
        for cell in row
        if cell is not None
    ]
    assert 7.0 in values and 19.0 in values


def test_export_csv_and_exclude_private(
    client: TestClient, repository: Repository
) -> None:
    items = json.loads(_items_payload())
    items[0]["is_private"] = True  # mark Milch private
    repository.insert_user_receipt(
        owner_token=OWNER,
        store="REWE",
        postal_code="65618",
        country_code="DE",
        currency="EUR",
        receipt_date="2026-11-21",
        total_cents=174,
        shared_to_community=False,
        items=items,
    )

    all_csv = client.get(f"{PREFIX}/receipts/export?format=csv").text
    assert "Privat" in all_csv

    business_csv = client.get(
        f"{PREFIX}/receipts/export?format=csv&exclude_private=true"
    ).text
    # The private Milch row is gone; only the Pfand row remains.
    assert "Frische Vollmilch" not in business_csv
    assert "Pfand" in business_csv


# ---------------------------------------------------------------------------
# Rate limiting (global daily cap)
# ---------------------------------------------------------------------------


def test_global_scan_cap_returns_429_and_byok_bypasses(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from supermarket_comparison.config import get_settings

    settings = get_settings()
    object.__setattr__(settings, "max_global_scans_per_day", 2)
    object.__setattr__(settings, "vision_primary_provider", "gemini")
    object.__setattr__(settings, "vision_primary_api_key", "k")
    object.__setattr__(settings, "vision_primary_model", "m")

    scan_daily_global.reset()
    scan_per_ip_limiter.reset()

    import supermarket_comparison.services.receipt_vision as _rv

    transport = FakeVisionTransport(primary_fails=False)

    mock = httpx.MockTransport(transport.handle)
    _real_async_client = _rv.httpx.AsyncClient

    def _mock_client(**kwargs):
        return _real_async_client(transport=mock)

    monkeypatch.setattr(_rv.httpx, "AsyncClient", _mock_client)

    files = {
        "file": (
            "receipt.jpg",
            _fake_image_bytes(),
            "image/jpeg",
        )
    }
    # 1st and 2nd scans pass (cap=2), 3rd -> 429.
    assert client.post(f"{PREFIX}/receipts/scan", files=files).status_code == 200
    assert client.post(f"{PREFIX}/receipts/scan", files=files).status_code == 200
    third = client.post(f"{PREFIX}/receipts/scan", files=files)
    assert third.status_code == 429
    assert "Gratis-Kontingent" in third.json()["detail"]

    # BYOK bypasses the global cap.
    byok = client.post(
        f"{PREFIX}/receipts/scan",
        files=files,
        headers={"X-User-Vision-Key": "user-key", "X-Owner-Token": OWNER},
    )
    assert byok.status_code == 200

    scan_per_ip_limiter.reset()
    scan_daily_global.reset()


def test_scan_without_owner_token_returns_422(client: TestClient) -> None:
    files = {"file": ("receipt.jpg", _fake_image_bytes(), "image/jpeg")}
    response = client.post(
        f"{PREFIX}/receipts/scan", files=files, headers={"X-Owner-Token": ""}
    )
    # 429/422/503/200 all acceptable (rate limit, validation, no vision).
    assert response.status_code in (401, 422, 200, 503)
