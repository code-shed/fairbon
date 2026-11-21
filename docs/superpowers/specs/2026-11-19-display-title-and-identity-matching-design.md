# Design — Anreicherung generischer Produkttitel & sauberes Produkt-Matching

Datum: 2026-11-19
Status: **Entwurf — zur Freigabe**

## 1. Absicht

Zwei verwandte Probleme bei heterogenen Kategorien (z. B. Bier):
1. Viele Angebote tragen als `name` nur den Gattungsbegriff („Bier"), obwohl
   Marke und Sorte in `brand`/offer-`description` stehen. Die Karte und das
   Modal zeigen dann nur „Bier".
2. Das Preisverlauf-Modal und die Historie matchen ohne EAN nur über den
   normalisierten Titel. Damit verschmelzen eine 0,5 l Dose Beck's (0,79 €),
   ein Sixpack (5,49 €) und ein Kasten (12,49 €) zu einem Produkt.

Ziel: ein angereicherter Anzeigetitel (`display_title`) plus Matching, das
Marke **und** Gebindegröße berücksichtigt — mit zwei Ansichten im Modal
(„Dieses Gebinde" / „Alle Sorten").

## 2. Ziele

- `build_display_title(title, brand, description)` in der Normalisierung,
  testbar, deterministisch.
- `display_title` auf Karte und Modal-Überschrift.
- Modal/History können nach strenger Identität (Marke + Name + Menge + Einheit)
  oder nach Kategorie (Name) filtern.
- Tests für `build_display_title` (Corona Extra, Desperados, Paulaner ohne
  Dopplung) und für getrennte Identitäts-Hashes bei unterschiedlichen Gebinden.
- `pytest` und `ruff` grün.

## 3. Nicht-Ziele

- Keine neue DB-Spalte für `display_title` (wird berechnet, nicht gespeichert).
- Keine DB-Migration der `name`-Spalte (Identität basiert bereits auf
  Marke + Name + Menge; nur das Matching in der API-Schicht wird angepasst).
- Keine ML-/Fuzzy-Matching-Änderung; Matching bleibt deterministisch.
- Kein neues Frontend-Framework; ES5 wie bisher.

## 4. Ausgangslage (verifiziert im Code)

- `product_key()` in `storage/repository.py` enthält bereits
  `normalize_title(name) | normalize_title(brand) | menge+einheit` → die
  DB-Identität ist korrekt. Der Merge passiert in `price_history()` und
  `price_insights()`, die nur auf `normalize_title(name)` filtern.
- `NormalizedProduct` hat kein `description`-Feld. Marktguru trägt die
  Sorte/Gebinde-Hinweise im offer-level `description` (z. B. „Streichzart
  in versch. Sorten … Je 250 g"), das nur in `_size_of` genutzt wird.
- `clean_brand()` existiert; `normalize_title()` (umlaut-gefaltet, lower-case)
  ist die Matching-Basis.

## 5. Ansätze

### Ansatz A — Strenges Matching als Default, Kategorie als Opt-in (gewählt)
Modal öffnet in „Dieses Gebinde" (Marke + Name + Menge + Einheit) und bietet
einen Tab „Alle Sorten" (nur Name). Karte zeigt `display_title`.

### Ansatz B — Nur streng
Einfacher, aber die Kategorie-Sicht (die bei Butter spannend ist) geht
verloren. Verworfen, weil der Nutzer beide Perspektiven will.

### Ansatz C — Brand-Filter nur im Modal, Historie bleibt name-basiert
Inkonsistent zwischen Modal und Historie. Verworfen.

## 6. Datenmodell

- `NormalizedProduct` bekommt ein optionales Feld `description: str | None`.
- Neues berechnetes Feld `display_title` (Pydantic `@computed_field`), das
  `build_display_title(name, brand, description)` aufruft. Dadurch ist es in
  der API-Response automatisch enthalten, ohne DB-Spalte.
- Marktguru setzt `description=as_text(raw.get("description"))` (offer-level).
  Kaufda hat keine separate Beschreibung → `None` (build_display_title fällt
  auf Name + Marke zurück).

## 7. Normalisierung `build_display_title(title, brand, description)`

Regeln (in dieser Reihenfolge):
1. `title` und `brand` bereinigen (`clean_brand` für Marke, strip für Titel).
2. Wenn `brand` vorhanden und nicht bereits (case-insensitive) in `title`
   enthalten → Marke voranstellen: `"{brand} {title}"`.
3. Hint-Extraktion aus `description`: kleine Menge bekannter Sorten-/Gebinde-
   Hinweise (`Pils`, `Gold`, `Helles`, `Alkoholfrei`, `Kasten`, `Sixpack`,
   `Dose`, `Flasche`, `0,33`, …). Nur anhängen, wenn im aktuellen Titel
   noch nicht enthalten (case-insensitive, umlaut-gefaltet).
4. Dopplungs-Schutz: niemals denselben Token zweimal; Marke nicht zweimal.
5. Leere/None-Eingaben gracefully behandeln (mindestens `title` zurückgeben).

## 8. Matching / API

- `price_history()` und `price_insights()`: neue optionale Parameter
  `brand`, `quantity`, `unit`. Wenn gesetzt, filtert auf
  `normalize_title(row["name"]) == normalize_title(name)`
  **und** `normalize_title(row["brand"]) == normalize_title(brand)`
  **und** `round(quantity,3)` + `unit` übereinstimmen.
- Wenn `brand`/`quantity`/`unit` nicht gesetzt → bisheriges Verhalten
  (Name-only, = „Alle Sorten").
- `product_key()` bleibt unverändert (bereits korrekt).

## 9. Frontend

- Karte: `offer.display_title || offer.name`.
- Modal-Überschrift: `display_title`.
- Modal: zwei Tabs „Dieses Gebinde" (ruft price-insights mit
  `brand`+`quantity`+`unit` des angeklickten Angebots) und „Alle Sorten"
  (ruft ohne diese Parameter, wie bisher). Die Läden-Liste (#detail-stores)
  nutzt dieselben Parameter wie der aktive Tab.

## 10. Tests

- `tests/test_matcher.py` (oder neues `test_display_title.py`):
  `build_display_title("Bier", "Corona Extra", None) == "Corona Extra Bier"`,
  `build_display_title("Original Bier", "Desperados", None) == "Desperados Original Bier"`,
  `build_display_title("Hefe-Weißbier", "Paulaner", None) == "Paulaner Hefe-Weißbier"` (keine Dopplung).
- `tests/test_storage.py` (oder neuer): `product_key` für zwei Angebote mit
  gleicher Marke/Name aber unterschiedlicher Menge (0.5 l Dose vs. 10 l Kasten)
  → unterschiedliche Keys.
- API: price-insights mit/ohne brand+quantity filtert korrekt (bestehende
  Tests erweitern).

## 11. Migration / Cleanup

Keine Schema-Migration. Bestehende `products`-Zeilen behalten `name`; die
Anzeige nutzt das berechnete `display_title`. Die Identität ist bereits
mengen-spezifisch, daher sind „Bier"-Cluster in der DB bereits getrennt —
der Merge war rein ein UI/API-Problem, das durch die neuen Filter behoben wird.

## 12. Verifikation

- `uv run pytest -q` grün, `uv run ruff check .` sauber.
- Manuell: Modal für Beck's 0,5 l Dose zeigt nur 0,5 l Dosen; Tab-Wechsel
  auf „Alle Sorten" zeigt alle Bier-Angebote; Karte zeigt angereicherten Titel.
