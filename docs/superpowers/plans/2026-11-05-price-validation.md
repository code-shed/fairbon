# Plausibilitätsprüfung Community-Preise — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Community- und Kassenbon-Preise werden vor der Veröffentlichung deterministisch geprüft; nur vom Admin freigegebene oder von drei Scouts bestätigte Preise erscheinen in Suche, Basket und Deckungsanzeige.

**Architecture:** Eine reine Prüffunktion (`services/price_validator.py`) bewertet Preis, Grundpreis, Warengruppen-Band und relative Abweichung. `CommunityStore` ruft sie beim Einfügen auf und setzt `pending` oder `pending_review`; eine zentrale Konstante `VISIBLE_STATUSES` steuert jede Leseabfrage. Admin-Endpunkte und ein Queue-Block im bestehenden Admin-Dialog schließen den Kreis.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLite (stdlib), pytest, ruff, ES5-Vanilla-JS (Frontend bleibt selbstständig).

**Spec:** `docs/superpowers/specs/2026-11-05-price-validation-design.md`

## Global Constraints

- Sichtbar sind **nur** `approved` und `verified` (Spec §7). `pending` und `pending_review` dürfen in Suche, Basket, `aggregated_for_query` und Coverage **nicht** auftauchen.
- Harte Grenzen: Preis `0.10 ≤ p ≤ 200.00`; Grundpreis `0.05 ≤ p ≤ 500.00` je kg/l; `quantity > 0`.
- Relative Prüfung erst ab `n ≥ 3` bestätigten Preisen für `(identity, store)`; Schwellen `> 1.8×` oder `< 0.55×` des Medians.
- Kassenbon: jede Zeile wird einzeln bewertet; eine Zeile blockiert den Bon nicht.
- Kein neues Frontend-Framework, keine externen Ressourcen, JS bleibt ES5 (keine `=>`, keine Template-Strings, kein `let`/`const`).
- Alle bestehenden 494 Tests bleiben grün; `ruff check .` und `ruff format --check .` sauber.
- Deutsche UI-Texte, deutsche Dezimalkommas.

## Review Focus

- **Preis 999,99 € für Milch:** muss `pending_review` werden und darf den Median nicht verschieben.
- **Erste Meldung überhaupt (n = 1):** darf nicht sichtbar werden, auch wenn sie plausibel ist.
- **Kassenbon mit 20 Zeilen, eine absurd:** die 19 plausiblen bleiben `pending`, die eine wird `pending_review`.
- **Bestätigung durch denselben Scout dreimal:** zählt nicht als drei Bestätigungen.
- **Admin lehnt ab:** Eintrag bleibt dauerhaft unsichtbar, auch nach weiteren Bestätigungen.

---

### Task 1: Warengruppen-Klassifikator

**Files:**
- Create: `supermarket_comparison/services/categories.py`
- Test: `tests/test_categories.py`

**Interfaces:**
- Consumes: `normalization.matcher.fold_umlauts`
- Produces: `classify_product(name: str, brand: str | None = None) -> str` (eine von `dairy`, `meat`, `produce`, `drinks`, `bakery`, `pantry`, `sweets`, `drugstore`, `other`); `unit_price_band(group: str) -> tuple[float, float] | None`

- [ ] **Step 1: Failing test**

```python
@pytest.mark.parametrize(
    ("name", "group"),
    [
        ("Bio Butter 250g", "dairy"),
        ("Hähnchenschenkel", "meat"),
        ("Bio Ingwer", "produce"),
        ("Cola XXL", "drinks"),
        ("Vollkornbrot", "bakery"),
        ("Spaghetti", "pantry"),
        ("Schokolade", "sweets"),
        ("Shampoo", "drugstore"),
        ("Batterien AA", "other"),
    ],
)
def test_classify_product(name, group):
    assert classify_product(name) == group
```

- [ ] **Step 2: Run** `uv run pytest tests/test_categories.py -v` → FAIL (module missing)

- [ ] **Step 3: Implement** `classify_product` mit Keyword-Sets (umlautgefaltet, Wortgrenzen über `split()`); `unit_price_band` liefert die Bänder aus der Spec: `dairy (0.30, 25.0)`, `meat (2.0, 80.0)`, `produce (0.20, 20.0)`, `drinks (0.15, 15.0)`, `bakery (0.50, 20.0)`, `pantry (0.30, 30.0)`, `sweets (1.0, 60.0)`, `drugstore (0.50, 300.0)`, `other (0.05, 500.0)`

- [ ] **Step 4: Run** denselben Test → PASS

- [ ] **Step 5: Commit** `feat: classify products into price bands`

---

### Task 2: Reine Prüffunktion

**Files:**
- Create: `supermarket_comparison/services/price_validator.py`
- Test: `tests/test_price_validator.py`

**Interfaces:**
- Consumes: `services.categories.classify_product`, `unit_price_band`
- Produces:
  ```python
  @dataclass(frozen=True)
  class PriceContext:
      name: str
      price: float
      unit: str | None = None
      quantity: float | None = None
      unit_price: float | None = None
      brand: str | None = None

  @dataclass(frozen=True)
  class ValidationResult:
      status: str          # "pending" | "pending_review"
      reasons: list[str]

  def validate_price(ctx: PriceContext, *, history: Sequence[float] = ()) -> ValidationResult
  ```

- [ ] **Step 1: Failing tests**

```python
def test_absurd_price_is_flagged():
    result = validate_price(
        PriceContext(
            name="Milch", price=999.99, unit="l", quantity=1.0, unit_price=999.99
        )
    )
    assert result.status == "pending_review"
    assert any("Grenze" in reason or "Band" in reason for reason in result.reasons)


def test_zero_price_is_flagged():
    assert (
        validate_price(PriceContext(name="Milch", price=0.01)).status
        == "pending_review"
    )


def test_plausible_butter_is_pending():
    result = validate_price(
        PriceContext(
            name="Bio Butter 250g",
            price=2.49,
            unit="kg",
            quantity=0.25,
            unit_price=9.96,
        )
    )
    assert result.status == "pending"
    assert result.reasons == []


def test_unit_price_outside_band_is_flagged():
    # 0.01 €/kg for dairy
    result = validate_price(
        PriceContext(
            name="Butter", price=0.01, unit="kg", quantity=1.0, unit_price=0.01
        )
    )
    assert result.status == "pending_review"


def test_relative_deviation_from_history_is_flagged():
    result = validate_price(
        PriceContext(
            name="Butter", price=8.99, unit="kg", quantity=0.25, unit_price=35.96
        ),
        history=[2.19, 2.29, 2.39],
    )
    assert result.status == "pending_review"
    assert any("Median" in reason for reason in result.reasons)


def test_history_below_three_is_ignored():
    result = validate_price(
        PriceContext(
            name="Butter", price=8.99, unit="kg", quantity=0.25, unit_price=35.96
        ),
        history=[2.19, 2.29],
    )
    assert result.status == "pending"
```

- [ ] **Step 2: Run** → FAIL

- [ ] **Step 3: Implement** in dieser Reihenfolge: absolute Grenzen → `quantity > 0` → Band über `unit_price` (nur kg/l) → relative Prüfung (`statistics.median(history)`, `len(history) >= 3`, `ratio > 1.8 or ratio < 0.55`). `status` = `pending_review`, sobald ein Grund existiert; Gründe als deutsche Klartext-Strings.

- [ ] **Step 4: Run** → PASS

- [ ] **Step 5: Commit** `feat: add deterministic community price validator`

---

### Task 3: Statusmodell und Sichtbarkeit im Store

**Files:**
- Modify: `supermarket_comparison/storage/schema.sql` (Spalten `review_reason`, `reviewed_at`, `reviewed_by`)
- Modify: `supermarket_comparison/storage/database.py` (SCHEMA_VERSION 8 + Migration der drei Spalten)
- Modify: `supermarket_comparison/storage/community.py`
- Test: `tests/test_community_visibility.py`

**Interfaces:**
- Produces: `VISIBLE_STATUSES: frozenset[str] = frozenset({"approved", "verified"})`; `CommunityStore.add_price(entry, *, history: Sequence[float] = ())` setzt `pending`/`pending_review` + `review_reason`; `approve(price_id, *, reviewer: str) -> dict | None`; `reject(price_id, *, reviewer: str, reason: str = "") -> dict | None`; `review_queue(status: str = "pending_review") -> list[dict]`; `approve_all_pending(*, reviewer: str) -> int`

- [ ] **Step 1: Failing tests**

```python
def test_pending_price_is_not_visible(repository):
    repository.community.add_price(CommunityPriceInput(name="Butter", store="lidl", price=2.49, postal_code="65618", quantity=0.25, unit="kg"))
    assert repository.community.aggregate(identity=..., store="lidl", postal_code="65618") is None


def test_approved_price_is_visible(repository):
    entry = repository.community.add_price(...)
    repository.community.approve(entry["id"], reviewer="admin")
    assert repository.community.aggregate(...)["median_price"] == 2.49


def test_three_distinct_scouts_verify(repository):
    entry = repository.community.add_price(...)
    for scout in ("B", "C", "D"):
        repository.community.confirm(entry["id"], scout)
    assert repository.community.get_price(entry["id"])["status"] == "verified"


def test_rejected_stays_hidden_after_confirm(repository):
    ... approve then reject, then confirm -> still rejected / not visible


def test_same_scout_twice_counts_once(repository):
    entry = repository.community.add_price(...)
    repository.community.confirm(entry["id"], "B")
    entry = repository.community.confirm(entry["id"], "B")
    assert entry["confirmations"] == 2          # author + B
    assert entry["status"] == "pending"


def test_approve_all_pending_skips_review(repository):
    # one plausible pending, one absurd pending_review
    assert repository.community.approve_all_pending(reviewer="admin") == 1
```

- [ ] **Step 2: Run** → FAIL

- [ ] **Step 3: Implement** `VISIBLE_STATUSES` in `aggregate`, `aggregated_for_query`; neue Methoden; `confirm` darf `rejected` nicht wiederbeleben; `approve_all_pending` nur `status = 'pending'`.

- [ ] **Step 4: Run** → PASS; zusätzlich `uv run pytest -q tests/test_crowd.py` (bestehende Tests ggf. an die strengere Sichtbarkeit anpassen)

- [ ] **Step 5: Commit** `feat: hide unconfirmed community prices`

---

### Task 4: Validator in die Aufnahmewege einhängen

**Files:**
- Modify: `supermarket_comparison/api/routes/crowd.py`
- Modify: `supermarket_comparison/services/receipt_import.py`
- Test: `tests/test_crowd_validation.py`

**Interfaces:**
- Consumes: `CommunityStore.add_price(..., history=...)`, `validate_price`
- Produces: `POST /api/v1/crowd/prices` antwortet zusätzlich mit `status` und `review_reason`; `import_receipt` zählt `pending`, `pending_review`, `rejected`

- [ ] **Step 1: Failing tests**

```python
def test_submission_reports_review_status(client):
    response = client.post(
        "/api/v1/crowd/prices",
        json={
            "name": "Milch",
            "store": "lidl",
            "price": 999.99,
            "postal_code": "65618",
        },
    )
    assert response.json()["price"]["status"] == "pending_review"
    assert response.json()["price"]["review_reason"]


def test_plausible_submission_is_pending_not_visible(client):
    payload = client.post(
        "/api/v1/crowd/prices",
        json={
            "name": "Butter",
            "store": "lidl",
            "price": 2.49,
            "postal_code": "65618",
            "quantity": 0.25,
            "unit": "kg",
        },
    ).json()
    assert payload["price"]["status"] == "pending"
    assert (
        client.get("/api/v1/crowd/coverage", params={"postal_code": "65618"}).json()[
            "observations"
        ]
        == 0
    )


def test_receipt_import_isolates_bad_lines(client):
    text = "LIDL\n65618\nBUTTER 250G 2,49\nMILCH 999,99\nSUMME 1002,48"
    result = client.post("/api/v1/crowd/receipts/text", json={"text": text}).json()
    assert result["imported"] == 2
    assert result["pending_review"] == 1
```

- [ ] **Step 2: Run** → FAIL

- [ ] **Step 3: Implement** — Store lädt vor `add_price` die bestätigte Historie (`SELECT price FROM community_prices WHERE identity=? AND store=? AND status IN (...)`), übergibt sie dem Validator; Route serialisiert `review_reason`; `import_receipt` liefert die Zähler.

- [ ] **Step 4: Run** → PASS

- [ ] **Step 5: Commit** `feat: validate community and receipt prices on submission`

---

### Task 5: Admin-Queue-API

**Files:**
- Modify: `supermarket_comparison/api/routes/crowd.py`
- Test: `tests/test_crowd_review_api.py`

**Interfaces:**
- Produces:
  - `GET /api/v1/crowd/review?status=pending_review&limit=50` → `{"items": [...], "counts": {"pending": n, "pending_review": n}}`
  - `POST /api/v1/crowd/prices/{id}/approve` → `{"price": {...}}`
  - `POST /api/v1/crowd/prices/{id}/reject` body `{"reason": "..."}` → `{"price": {...}}`
  - `POST /api/v1/crowd/review/approve-all` → `{"approved": n}` (nur `pending`)

- [ ] **Step 1: Failing tests**

```python
def test_review_queue_lists_anomalies(client):
    submit(name="Milch", price=999.99)  # -> pending_review
    submit(name="Butter", price=2.49)  # -> pending
    queue = client.get(
        "/api/v1/crowd/review", params={"status": "pending_review"}
    ).json()
    assert queue["counts"] == {"pending": 1, "pending_review": 1}
    assert [item["name"] for item in queue["items"]] == ["Milch"]


def test_approve_makes_price_visible(client):
    price_id = submit(name="Butter", price=2.49)["id"]
    client.post(f"/api/v1/crowd/prices/{price_id}/approve")
    coverage = client.get(
        "/api/v1/crowd/coverage", params={"postal_code": "65618"}
    ).json()
    assert coverage["observations"] == 1


def test_reject_keeps_price_hidden(client):
    price_id = submit(name="Butter", price=2.49)["id"]
    client.post(f"/api/v1/crowd/prices/{price_id}/reject", json={"reason": "Test"})
    assert (
        client.get("/api/v1/crowd/coverage", params={"postal_code": "65618"}).json()[
            "observations"
        ]
        == 0
    )


def test_approve_all_only_touches_pending(client):
    submit(name="Butter", price=2.49)
    submit(name="Milch", price=999.99)
    assert client.post("/api/v1/crowd/review/approve-all").json() == {"approved": 1}


def test_unknown_price_returns_404(client):
    assert client.post("/api/v1/crowd/prices/nope/approve").status_code == 404
```

- [ ] **Step 2: Run** → FAIL

- [ ] **Step 3: Implement** die vier Routen; `reviewer` = `"admin"` (Gate schützt bereits); 404 bei unbekannter ID.

- [ ] **Step 4: Run** → PASS

- [ ] **Step 5: Commit** `feat: add community review queue endpoints`

---

### Task 6: Suche und Basket respektieren die Sichtbarkeit

**Files:**
- Test: `tests/test_community_basket.py`
- Modify (nur falls nötig): `supermarket_comparison/services/aggregator.py`

**Interfaces:**
- Consumes: `CommunityStore.aggregated_for_query` (liefert nur sichtbare)

- [ ] **Step 1: Failing tests**

```python
@pytest.mark.asyncio
async def test_pending_price_never_reaches_search(repository):
    repository.community.add_price(butter_249)  # pending
    result = await aggregator(repository).search_ranked(
        query="butter", postal_code="65618"
    )
    assert [i for i in result.items if i.product.source == "community"] == []


@pytest.mark.asyncio
async def test_pending_review_price_is_ignored_by_basket(repository):
    repository.community.add_price(milk_999)  # pending_review
    plan = await aggregator(repository).optimize_basket(
        items=["Milch"], postal_code="65618", include_standard=True
    )
    assert all(
        line.product.source != "community"
        for option in (plan.option_a, plan.option_b)
        for group in option.stores
        for line in group.lines
    )


@pytest.mark.asyncio
async def test_approved_price_reaches_search_and_basket(repository):
    entry = repository.community.add_price(butter_249)
    repository.community.approve(entry["id"], reviewer="admin")
    result = await aggregator(repository).search_ranked(
        query="butter", postal_code="65618"
    )
    assert any(
        i.product.source == "community" and i.product.price == 2.49
        for i in result.items
    )
```

Hinweis: Da nur sichtbare Preise die API erreichen, brauchen die Produktkarten
keine eigene Filterlogik — der Test in Task 7 prüft nur die Queue-UI.

- [ ] **Step 2: Run** → FAIL (falls Task 3 korrekt ist, ggf. schon grün — dann Test behalten und als Regressionsschutz committen)

- [ ] **Step 3: Bei Bedarf** `_fetch_community` auf sichtbare Aggregation begrenzen.

- [ ] **Step 4: Run** → PASS

- [ ] **Step 5: Commit** `test: pin community visibility in search and basket`

---

### Task 7: Admin-Queue im UI

**Files:**
- Modify: `supermarket_comparison/api/templates/index.html`
- Test: `tests/test_ui.py` (Marker) + DOM-Smoke

**Interfaces:**
- Consumes: Task-5-Endpunkte

- [ ] **Step 1: Failing test**

```python
def test_ui_contains_review_queue(client):
    html = client.get("/").text
    assert 'id="admin-review"' in html
    assert "/api/v1/crowd/review" in html
    assert "Alle plausiblen freigeben" in html
```

- [ ] **Step 2: Run** → FAIL

- [ ] **Step 3: Implement** Block im Admin-Modal: Zähler, Liste (Produkt, Markt, Preis, Grund, Freigeben/Ablehnen), Button „Alle plausiblen freigeben". Danach `loadReviewQueue()` beim Öffnen.

- [ ] **Step 4: Run** → PASS

- [ ] **Step 5: Commit** `feat: admin review queue in the UI`

---

### Task 8: Doku und Gesamtprüfung

**Files:**
- Modify: `README.md`, `TASKS.md`, `DESIGN.md` (Komponente `.review-item`)

- [ ] **Step 1:** README-Abschnitt „Community-Preise" um Prüfregeln, Statusmodell und Admin-Queue ergänzen.
- [ ] **Step 2:** TASKS.md Eintrag „Iteration 11" mit den Meilensteinen.
- [ ] **Step 3:** `uv run pytest -q` → alle Tests grün (≥ 494 + neue).
- [ ] **Step 4:** `uv run ruff check . && uv run ruff format --check .` → sauber.
- [ ] **Step 5:** `python -m supermarket_comparison.cli cleanup` und ein Live-Start mit Testmeldung (999,99 € → unsichtbar).
- [ ] **Step 6: Commit** `docs: document community price validation`
