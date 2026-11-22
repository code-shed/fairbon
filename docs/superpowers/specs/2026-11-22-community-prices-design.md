# Community prices visible in the price comparison — Design

Date: 2026-11-22
Status: approved by the product owner in conversation

## Intent and why

Products uploaded through receipt scans must appear in the price
comparison. Today they never do: every price inserted from a receipt
starts as `pending` in `community_prices` and only rows with status
`approved` (admin) or `verified` (3 distinct scout confirmations,
the uploader's own counts as 1) are served by
`CommunityStore.aggregated_for_query`. A single user can never reach
the threshold, so their own scanned prices stay invisible forever
(28 rows in the live database sit in `pending`).

Price sources are exactly two from now on: prices from the user's own
uploaded receipts (community prices) and OpenPrice
(prices.openfoodfacts.org). Marktguru is not pulled anymore (its
scrapers were already removed; only stale comments remain). The UI
makes no distinction between sources and never mentions them.

## Goals

- Saving a receipt with "share with community" makes its prices
  visible in the price comparison immediately.
- Implausible prices (outliers flagged by the validator) still go to
  the review queue instead of silently polluting the comparison.
- Existing pending rows from the user's own receipts become visible
  (one-time backfill).
- No source badges or source wording in the UI.

## Non-goals

- Changing the crowd-confirmation flow for future multi-scout setups
  (scouts can still confirm/review; the threshold stays 3).
- OpenPrice integration changes (already implemented via
  `StandardPriceService`, source `openprices`).
- PLZ filtering changes (community prices stay postal-code scoped,
  consistent with OpenPrice observations).

## Approaches

1. **Auto-verify own receipt prices on save** (chosen). The uploader
   has already reviewed the scanned items in the editable preview
   before saving, so their own contribution is trusted. Flagged
   outliers keep going to the review queue.
2. Lower `VERIFY_THRESHOLD` to 1 — also unblocks today, but weakens
   the anti-bad-data design for every future scout, not just own
   receipts.
3. Admin approves manually — unblocks the existing rows, but breaks
   the flow again for every future upload.

Approach 1 with a one-time backfill of the existing rows.

## Design

- Receipt save (`share_anonymized=true`): after `add_price` inserts a
  price whose validator verdict is plausible, promote it to `verified`
  directly. Flagged verdicts stay in the queue as today.
- Backfill: one-time migration flips existing `pending` rows that came
  from receipts and carry no `review_reason` to `verified`.
- Cleanup: remove the stale `marktguru` references in
  `models/product.py` doc strings/slugs.
- Search behaviour itself is unchanged (`aggregated_for_query` already
  merges visible rows; PLZ filter stays).

## Tests

- Saving a shared receipt makes its prices appear in the ranked search.
- A flagged outlier stays hidden (review queue).
- Demo receipts never feed the community (unchanged guarantee).
- Backfill promotes only plausible receipt rows, idempotently.
