> **Archived:** historical German design/plan record (pre-V1.0). Active documentation is in English.

# Anreicherung generischer Produkttitel & sauberes Produkt-Matching

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generische Titel („Bier") mit Marke und Sortenhinweisen anreichern (`display_title`) und das Preisverlauf-Modal/ die Historie nach Marke + Gebindegröße trennen (Tabs „Dieses Gebinde" / „Alle Sorten").

**Architecture:** `build_display_title` in der Normalisierung; optionales `description`-Feld + berechnetes `display_title` auf `NormalizedProduct`; API-Filter in `price_history`/`price_insights` (brand/quantity/unit); Frontend nutzt `display_title` und Tabs. Keine DB-Schema-Migration.

**Tech Stack:** Python 3.12, Pydantic v2, FastAPI, SQLite, pytest, ruff, ES5-Vanilla-JS (inline).

**Spec:** `docs/superpowers/specs/2026-11-19-display-title-and-identity-matching-design.md`

## Global Constraints

- JS bleibt ES5 (kein `let`/`const`, keine Arrow-Functions, keine Template-Strings).
- Keine externen Ressourcen, kein Build-Step.
- `product_key()` bleibt unverändert (bereits mengen-spezifisch).
- Alle bestehenden 629 Tests bleiben grün; neue Tests werden ergänzt.
- Kein Git-Repository → keine Commit-Schritte; Änderungen als Working-Tree-Edits.
- Keine Schema-Migration; `display_title` wird berechnet, nicht gespeichert.

## Review Focus

- `build_display_title` muss Dopplungen vermeiden („Paulaner Paulaner …") und leere/None-Eingaben graceful behandeln.
- Der API-Filter darf die Kategorie-Ansicht („Alle Sorten") nicht brechen: ohne brand/quantity/unit bleibt das Verhalten name-basiert.
- `description` ist optional; fehlende Werte dürfen `display_title` nicht crashen.
- Der Frontend-Tab-Wechsel muss die Läden-Liste mitaktualisieren (nicht nur den Chart).
- `@computed_field` muss in der JSON-Response erscheinen (Pydantic v2 Serialisierung prüfen).

---

### Task 1: `build_display_title` in der Normalisierung

**Files:**
- Modify: `supermarket_comparison/normalization/matcher.py` (Funktion hinzufügen + Export)
- Test: `tests/test_matcher.py` (neue Tests)

**Interfaces:**
- Produces: `build_display_title(title, brand=None, description=None) -> str`

- [ ] **Step 1: Failing tests** in `tests/test_matcher.py`:
  `build_display_title("Bier", "Corona Extra", None) == "Corona Extra Bier"`,
  `build_display_title("Original Bier", "Desperados", None) == "Desperados Original Bier"`,
  `build_display_title("Hefe-Weißbier", "Paulaner", None) == "Paulaner Hefe-Weißbier"`,
  `build_display_title("Bier", None, None) == "Bier"`,
  `build_display_title("Bier", "Corona Extra", "0,33 l Dose")` enthält „Dose" wenn noch nicht im Titel.

- [ ] **Step 2: Run** `uv run pytest tests/test_matcher.py -q` → FAIL.

- [ ] **Step 3: Implement** `build_display_title` in `matcher.py`:
  Generische-Erkennung über `brand not in title` (case-insensitive, umlaut-gefaltet);
  Marke voranstellen wenn fehlend; Hint-Extraktion aus `description` (bekannte
  Sorten-/Gebinde-Hinweise); Dopplungs-Schutz; graceful bei None/leer.
  Export in `__all__`/Import-Pfad.

- [ ] **Step 4: Run** → PASS.

---

### Task 2: `description`-Feld + `display_title` auf `NormalizedProduct`

**Files:**
- Modify: `supermarket_comparison/models/product.py`
- Modify: `supermarket_comparison/scrapers/marktguru.py` (description setzen)
- Test: `tests/test_models.py` (oder bestehende Model-Tests) für computed field

**Interfaces:**
- Consumes: `build_display_title` aus Task 1
- Produces: `NormalizedProduct.description`, `NormalizedProduct.display_title` (computed)

- [ ] **Step 1: Failing test** — `NormalizedProduct(name="Bier", brand="Corona Extra", price=1.0).display_title == "Corona Extra Bier"` und Serialisierung enthält `display_title`.

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement** — Feld `description: str | None = None` hinzufügen;
  `@computed_field @property def display_title(self) -> str` mit
  `build_display_title(self.name, self.brand, self.description)`.
  Marktguru: `description=as_text(raw.get("description"))`.

- [ ] **Step 4: Run** → PASS.

---

### Task 3: API-Matching nach Marke + Gebinde

**Files:**
- Modify: `supermarket_comparison/storage/repository.py` (`price_history`-Signatur + Filter)
- Modify: `supermarket_comparison/api/routes/history.py` (Query-Params in `product_history` und `price_insights`)
- Test: `tests/test_storage.py` / `tests/test_system_api.py` (Filter-Verhalten)

**Interfaces:**
- Consumes: `normalize_title` (bereits importiert)
- Produces: optionale Filter `brand`, `quantity`, `unit` in beiden Endpunkten

- [ ] **Step 1: Failing tests** — `price_history(name="Bier", brand="Beck's", quantity=0.5, unit="l")` liefert nur passende Gebinde; ohne Filter wie bisher.

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement** — `price_history`-Signatur erweitern; Filter auf
  `normalize_title(row["name"]) == normalize_title(name)` **und**
  (wenn brand) `normalize_title(row["brand"]) == normalize_title(brand)` **und**
  (wenn quantity+unit) `round(row["quantity"],3)` + `row["unit"]` übereinstimmen.
  Routes: Query-Params `brand`, `quantity`, `unit` durchreichen.
  `aprice_history` reicht `**kwargs` durch (bereits).

- [ ] **Step 4: Run** → PASS.

---

### Task 4: Frontend — `display_title` und Tabs

**Files:**
- Modify: `supermarket_comparison/api/templates/index.html`

**Interfaces:**
- Consumes: `offer.display_title` aus API-Response; Query-Params `brand`/`quantity`/`unit` für price-insights.

- [ ] **Step 1: Karte + Modal-Überschrift** nutzen `offer.display_title || offer.name`.
- [ ] **Step 2: Tabs** im Detail-Modal („Dieses Gebinde" / „Alle Sorten"); `loadInsights` baut die URL je nach aktivem Tab (mit/ohne brand+quantity+unit); Läden-Liste folgt dem Tab.
- [ ] **Step 3: Regressionsprüfung** — pytest (629 passed), ruff clean, HTML/JS-Parse OK, manuelle Prüfung.

---

### Task 5: Tests für Identity-Hashes

**Files:**
- Modify: `tests/test_storage.py` (oder neues Test-Modul)

- [ ] **Step 1: Tests** — `product_key` für zwei Angebote mit gleicher Marke/Name
  aber unterschiedlicher Menge (0,5 l Dose vs. 10 l Kasten) → unterschiedliche Keys;
  gleiche Menge → gleicher Key.
- [ ] **Step 2: Run** → PASS.

---

## Self-Review

1. **Spec-Coverage:** build_display_title (Task 1), description+display_title (Task 2),
   Matching (Task 3), Frontend (Task 4), Tests (Task 1/2/3/5), Migration-Hinweis
   (keine Migration nötig, dokumentiert). Abgedeckt.
2. **Step-Scan:** Jede Task hat Test→Implement→Verify; Frontend-Task hat manuelle
   Verifikation statt automatischem Test (kein JS-Test-Harness) — dokumentiert.
3. **Type-Konsistenz:** `build_display_title(title, brand=None, description=None) -> str`
   überall gleich; `price_history(..., brand=None, quantity=None, unit=None)` gleich.
4. **Review Focus:** Alle fünf Punkte (Dopplung, Kategorie-Ansicht, description,
   Tab-Wechsel, computed_field-Serialisierung) haben zugehörige Tests/Verifikation.
5. **Proportion:** Plan ist länger als der Code, aber die Tasks sind eigenständig
   testbar; Frontend-Task bleibt ein Task (eng gekoppelt CSS→HTML→JS).

---

**Execution Handoff:** Plan gespeichert unter
`docs/superpowers/plans/2026-11-19-display-title-and-identity-matching.md`.
Du hast bereits **Native** gewählt. Soll ich ihn so umsetzen?
