> **Archived:** historical German design/plan record (pre-V1.0). Active documentation is in English.

# Design — Plausibilitätsprüfung für Community-Preise (Strict Mode)

Datum: 2026-11-05
Status: **freigegeben (2026-11-05) — Variante A + C**

## 1. Absicht

Ein von der Community gemeldeter oder aus einem Kassenbon importierter Preis
darf **niemals ungeprüft** in Suche oder Smart Basket erscheinen. Im Zweifel
zeigen wir lieber gar keinen Preis als einen falschen. Bestätigung erfolgt
durch einen Admin oder drei unabhängige Scouts.

## 2. Ziele

- Offensichtliche Fehler (Tippfehler, 999,99 €, Faktor-Ausreißer) landen in
  einer Moderations-Queue und werden nicht sichtbar.
- Nur bestätigte Preise (`approved`, `verified`) fließen in Median, Suche,
  Deckungsanzeige und Basket ein.
- Jede Entscheidung ist erklärbar (Grund wird gespeichert und im Admin-UI
  angezeigt).
- Kassenbon-Import: eine falsche Zeile blockiert nicht den ganzen Bon.

## 3. Nicht-Ziele

- Kein Nutzer-Login, keine Reputation pro Scout (wir bleiben anonym).
- Kein Machine-Learning-Modell; die Prüfung ist deterministisch und testbar.
- Keine Preisfreigabe ohne Admin oder drei Scouts (auch nicht „nur kurz").

## 4. Ausgangslage (verifiziert im Code)

- `CommunityStore.aggregate()` nimmt **alle** nicht-abgelehnten Zeilen. Bei der
  ersten Meldung ist n = 1, ein einzelner Ausreißer wird sofort Median.
- `community_prices` hat **keine Kategorie**; nur Name, Marke, Menge, Einheit,
  Preis und `unit_price` (€/kg bzw. €/l) sind normalisiert vorhanden.
- Status heute: `pending` (sichtbar), `verified` ab 3 Bestätigungen,
  `rejected`.
- Der Kassenbon-Import ruft `add_price` pro Zeile auf, ohne Prüfung.

## 5. Verworfene Ansätze

| Ansatz | Warum verworfen |
|---|---|
| Nur Median beim Aggregieren | Wirkt erst ab n ≥ 3; bei n = 1 wirkungslos. |
| Reiner Z-Score/MAD | Kaltstart blind, für Nutzer nicht nachvollziehbar. |
| Kategorie-Bänder allein | Kategorie fehlt im Datenmodell; Bänder wären geraten. |

## 6. Gewählter Ansatz: gestaffelte Prüfung (Strict)

**Schicht 1 — harte Grenzen (immer):**
- Preis 0,10 € ≤ p ≤ 200,00 €
- Grundpreis 0,05 €/kg(l) ≤ p ≤ 500,00 €/kg(l), wenn berechenbar
- `quantity` > 0, `unit` in {kg, l, stueck}

**Schicht 2 — Warengruppen-Band (immer):**
- Neuer Klassifikator `services/categories.py` (Port der Frontend-Keyword-
  Buckets): Molkerei, Fleisch/Fisch, Obst/Gemüse, Getränke, Backwaren, Vorrat,
  Süßes, Drogerie, Sonstiges.
- Bandbreiten für den **Grundpreis** je Gruppe (breit, konservativ), z. B.
  Molkerei 0,30–25 €/kg, Getränke 0,20–15 €/l, Drogerie 0,50–200 €/Stück.
- Außerhalb → `pending_review`.

**Schicht 3 — relativer Vergleich (ab n ≥ 3 bestätigten Preisen):**
- Median der bestätigten Preise für `(identity, store)` (PLZ-unabhängig, weil
  sonst zu dünn).
- Abweichung > 1,8× nach oben oder < 0,55× nach unten → `pending_review`.

Jede Ablehnung speichert `review_reason` (z. B. „Grundpreis 0,01 €/kg außerhalb
des Molkerei-Bands 0,30–25,00 €/kg").

## 7. Statusmodell (eine einzige Sichtbarkeitsregel)

```
pending_review ──approve──► approved
      │ reject                    ▲
      ▼                           │
   rejected                3 Scouts (verified)
pending ──3 distinct scouts──► verified
```

- **Sichtbar** (Median, Suche, Basket, Coverage): nur `approved` + `verified`.
- `pending` und `pending_review` sind unsichtbar. Ein frisch gemeldeter Preis
  erscheint also erst nach Admin-Freigabe oder drei Scout-Bestätigungen.
- `rejected` bleibt für Audits gespeichert.

Konstante `VISIBLE_STATUSES = {"approved", "verified"}` in
`storage/community.py`; alle Abfragen nutzen sie.

## 8. API

- `POST /api/v1/crowd/prices` → Antwort enthält `status` und `review_reason`,
  damit die UI „wird geprüft" erklären kann.
- `GET /api/v1/crowd/review?status=pending_review` → Queue (Admin).
- `POST /api/v1/crowd/prices/{id}/approve` → `approved`.
- `POST /api/v1/crowd/prices/{id}/reject` → `rejected` (mit optionalem Grund).
- `POST /api/v1/crowd/prices/{id}/confirm` bleibt; drei unterschiedliche
  Scouts heben `pending`/`pending_review` nach `verified`.
- Alle Admin-Endpunkte liegen hinter dem bestehenden Passwort-Gate.

## 9. UI

- **Admin-Modal** erhält den Block „Prüf-Queue": Liste mit Produkt, Markt,
  Preis, Grund, Buttons „Freigeben" / „Ablehnen".
- **Produktkarten**: kein Badge und kein Preis für unsichtbare Einträge; die
  Meldung bestätigt dem Nutzer nur „Danke, wird geprüft".
- **Deckungsanzeige** zählt nur sichtbare Preise.

## 10. Migration

- Schema v8: Spalten `review_reason TEXT`, `reviewed_at TEXT`, `reviewed_by TEXT`.
- Bestehende `pending`-Zeilen bleiben erhalten, werden aber ab sofort
  **nicht mehr angezeigt** (keine Datenlöschung). `verified`/`rejected`
  unverändert.

## 11. Tests

- Validator: 999,99 €, 0,01 €, falscher Grundpreis, plausibler Butterpreis,
  Band-Grenzen, relative Abweichung, Kassenbon-Zeile isoliert.
- Sichtbarkeit: `pending`/`pending_review` erscheinen nicht in
  `aggregated_for_query`, Suche und Basket.
- Admin-Flow: Queue, approve → sichtbar, reject → dauerhaft unsichtbar.
- Bestehende 494 Tests bleiben grün.

## 12. Entscheidungen

- **Variante A + C** freigegeben: strikte Sichtbarkeit (nur `approved`/
  `verified`) plus **Sammelfreigabe** für alle plausiblen `pending`-Einträge.
- Bandbreiten starten konservativ und werden später aus echten Daten nachgezogen.
- `pending_review` wird **nicht** von der Sammelfreigabe erfasst — Anomalien
  bleiben Einzelfallentscheidungen.
