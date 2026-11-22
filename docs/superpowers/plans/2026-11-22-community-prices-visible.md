# Community prices visible in the price comparison — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prices from the user's own shared receipts appear in the price comparison immediately, without giving up the outlier review queue.

**Architecture:** `CommunityStore.add_price` gains an `auto_verify` flag used only by the receipt-save path; plausible prices insert directly as `verified`, flagged ones still quarantine as `pending_review`. A startup migration backfills existing `pending` receipt rows. Stale marktguru references are removed.

**Tech Stack:** Python 3.12, FastAPI, sqlite (Repository/Database), pytest.

**Spec:** `docs/superpowers/specs/2026-11-22-community-prices-design.md`

## Global Constraints

- UI language German, repo/docs English.
- Demo receipts never feed the community (`is_demo` + `share_anonymized=false`).
- `scout_id=None` on the receipt path (no owner linkage) — unchanged.
- Crowd/scout submissions (`routes/crowd.py`, `services/receipt_import.py`) keep the existing `pending` flow.
- No frontend changes in this plan (no service-worker bump needed).

## Review Focus

- **Flagged outlier must stay hidden:** a receipt item with price above `MAX_PRICE` (200.00 €) writes `pending_review`, never `verified` — pinned in Task 1's outlier test.
- **Crowd flow untouched:** a scout submission without `auto_verify` still lands as `pending` — pinned by the existing crowd tests staying green (Task 1 step 4 runs them).
- **Backfill never promotes flagged rows:** a `pending_review` receipt row survives the migration — pinned in Task 2.
- **Backfill never promotes other sources:** a `pending` row with `source='scout'` survives — pinned in Task 2.
- **Idempotency:** second migration run changes nothing — pinned in Task 2 by re-opening the database.

---

### Task 1: Auto-verify prices from shared receipts

**Files:**
- Modify: `supermarket_comparison/storage/community.py:128-196` (`add_price`)
- Modify: `supermarket_comparison/api/routes/receipts.py:668-705` (`_share_to_community`)
- Test: `tests/test_receipts_v2.py`

**Interfaces:**
- Produces: `CommunityStore.add_price(entry: CommunityPriceInput, *, history: Sequence[float] | None = None, auto_verify: bool = False) -> dict[str, Any]` — with `auto_verify=True` and a plausible verdict the inserted row has `status='verified'`; flagged verdicts still insert `pending_review`.
- Consumes: existing `CommunityStore.aggregated_for_query(query=..., postal_code=...)` (unchanged) to prove visibility.

- [ ] **Step 1: Write the failing tests** (append near `test_save_with_optin_shares_only_eligible_lines_without_owner`)

```python
def test_shared_receipt_prices_are_visible_immediately(
    client: TestClient, repository: Repository
) -> None:
    client.post(
        f"{PREFIX}/receipts",
        data={
            "store": "penny",
            "postal_code": "65618",
            "currency": "EUR",
            "receipt_date": "2026-11-22",
            "total_cents": 149,
            "share_anonymized": "true",
            "is_demo": "false",
            "items_json": json.dumps(
                [
                    {
                        "raw_text": "Milch 1,49 A",
                        "normalized_name": "Milch",
                        "category": "Lebensmittel",
                        "quantity": 1.0,
                        "unit": "stueck",
                        "price_cents": 149,
                    }
                ]
            ),
        },
    )

    found = repository.community.aggregated_for_query(
        query="Milch", postal_code="65618"
    )
    assert [entry["store"] for entry in found] == ["penny"]


def test_flagged_receipt_price_stays_in_review(
    client: TestClient, repository: Repository
) -> None:
    client.post(
        f"{PREFIX}/receipts",
        data={
            "store": "penny",
            "postal_code": "65618",
            "currency": "EUR",
            "receipt_date": "2026-11-22",
            "total_cents": 500000,
            "share_anonymized": "true",
            "is_demo": "false",
            "items_json": json.dumps(
                [
                    {
                        "raw_text": "Gold 5000,00",
                        "normalized_name": "Gold",
                        "category": "Sonstiges",
                        "quantity": 1.0,
                        "unit": "stueck",
                        "price_cents": 500000,
                    }
                ]
            ),
        },
    )

    assert repository.community.aggregated_for_query(
        query="Gold", postal_code="65618"
    ) == []
    rows = repository.db.query(
        "SELECT status FROM community_prices WHERE name = 'Gold'"
    )
    assert rows and rows[0]["status"] == "pending_review"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest -q tests/test_receipts_v2.py -k "visible_immediately or stays_in_review"`
Expected: both FAIL (first: `aggregated_for_query` returns `[]` because the row is `pending`; second may already pass on the review side — if so, keep it as a guard for Step 3).

- [ ] **Step 3: Implement `auto_verify` in `add_price` and use it in the receipt path**

In `community.py::add_price`: add keyword parameter `auto_verify: bool = False`. Choose the inserted status as `"verified"` when `auto_verify and verdict.status == "pending"`, otherwise keep `verdict.status`. No other changes to the method.

In `routes/receipts.py::_share_to_community`: pass `auto_verify=True` at both call sites (`asyncio.to_thread(community.add_price, entry)` → use a lambda or partial to include the keyword; the defensive non-thread branch gets it too). Update the comment above the call to say plausible own-receipt prices are verified directly, flagged ones quarantine.

- [ ] **Step 4: Run tests to verify they pass, plus the crowd guards**

Run: `uv run pytest -q tests/test_receipts_v2.py -k "visible_immediately or stays_in_review"`
Expected: PASS
Run: `uv run pytest -q tests/test_crowd.py tests/test_crowd_review_api.py tests/test_community_hardening.py`
Expected: PASS (scout submissions still start `pending`)

- [ ] **Step 5: Commit**

```bash
git add supermarket_comparison/storage/community.py supermarket_comparison/api/routes/receipts.py tests/test_receipts_v2.py
git commit -m "Verify own receipt prices immediately for the price comparison"
```

### Task 2: Backfill existing pending receipt rows

**Files:**
- Modify: `supermarket_comparison/storage/database.py:52-91` (`_migrate`)
- Test: `tests/test_backup.py` or a new `tests/test_migrations.py`

**Interfaces:**
- Consumes: `Database(path)` runs `_migrate` on init (unchanged signature).
- Produces: idempotent startup step promoting `pending` receipt rows to `verified`.

- [ ] **Step 1: Write the failing test** (new file `tests/test_migrations.py`)

```python
def test_migrate_promotes_only_plausible_receipt_rows(tmp_path) -> None:
    from supermarket_comparison.storage import Database

    path = str(tmp_path / "migrate.db")
    database = Database(path)
    conn = database._conn
    now = "2026-11-22T00:00:00"
    for source, status, name in (
        ("receipt", "pending", "Milch"),
        ("receipt", "pending_review", "Gold"),
        ("scout", "pending", "Brot"),
    ):
        conn.execute(
            "INSERT INTO community_prices (id, identity, ean, name, store,"
            " price, postal_code, source, status, confirmations, created_at,"
            " updated_at) VALUES (?, ?, NULL, ?, 'penny', 1.0, '65618', ?,"
            " ?, 1, ?, ?)",
            (f"id-{name}", f"identity-{name}", name, source, status, now, now),
        )
    conn.commit()
    database.close()

    database = Database(path)  # second init runs _migrate again (idempotency)

    def statuses():
        rows = database._conn.execute(
            "SELECT name, status FROM community_prices ORDER BY name"
        ).fetchall()
        return {row["name"]: row["status"] for row in rows}

    assert statuses() == {
        "Milch": "verified",        # plausible receipt row promoted
        "Gold": "pending_review",   # flagged row untouched
        "Brot": "pending",          # other sources untouched
    }
    database.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest -q tests/test_migrations.py -v`
Expected: FAIL with `Milch == pending` (no promotion yet)

- [ ] **Step 3: Implement the promotion in `_migrate`**

Append after the existing community column loop in `database.py::_migrate`:

```python
# Own-receipt prices are inserted as verified since <commit>; promote any
# rows older saves left pending.  Flagged rows (pending_review) and other
# sources (scout) are deliberately untouched.  Idempotent.
self._conn.execute(
    """
    UPDATE community_prices
       SET status = 'verified', updated_at = ?
     WHERE source = 'receipt' AND status = 'pending'
    """
)
```

with the current ISO timestamp for `updated_at` (reuse the same helper style `_iso_now` uses in `community.py`, or `datetime.now(timezone.utc).isoformat()` inline). Commit once at the end as the existing code does.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest -q tests/test_migrations.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add supermarket_comparison/storage/database.py tests/test_migrations.py
git commit -m "Backfill pending receipt prices to verified on startup"
```

### Task 3: Remove stale marktguru references

**Files:**
- Modify: `supermarket_comparison/models/product.py:58-92`

**Interfaces:** none (doc-string cleanup only; `source` values in code/tests are unchanged).

- [ ] **Step 1: Clean the two stale doc lines**

Line 60 `description="lidl, edeka, rewe, marktguru, openfoodfacts"` → `description="lidl, edeka, rewe, openfoodfacts"`; line 89 ``(``marktguru``, ``openprices``, ...)`` → ``(``openprices``, ``openfoodfacts``, ...)``. Grep the package for remaining `marktguru` mentions afterwards: `grep -rn marktguru supermarket_comparison` must return nothing.

- [ ] **Step 2: Verify nothing broke**

Run: `uv run pytest -q` and `uv run ruff check .`
Expected: all tests PASS, lint clean

- [ ] **Step 3: Commit**

```bash
git add supermarket_comparison/models/product.py
git commit -m "Drop stale marktguru references from product docs"
```

### Task 4: Live verification on the main server

- [ ] **Step 1: Restart the main server with `.env` sourced (as before) and confirm the backfill hit the live DB:** 28 `receipt|pending` rows become `receipt|verified` (`sqlite3 "$db" "SELECT status, COUNT(*) FROM community_prices GROUP BY status;"`).

- [ ] **Step 2: End-to-end check:** search via API for a product from the user's receipts (e.g. `Vitamin-C-Brausetabletten`) with PLZ 65618 → appears in `/api/v1/products/search/ranked` results. Push all commits.
