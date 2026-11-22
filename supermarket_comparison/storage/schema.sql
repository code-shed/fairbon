-- SQLite schema for price history and anonymised search statistics.
--
-- Design notes:
--  * `products` is keyed by a deterministic `key` (EAN when known, otherwise a
--    hash of the normalised name + brand). No EAN is ever invented.
--  * `price_points` stores one observation per (product, store, day, validity
--    window); re-running the same search on the same day is idempotent.
--  * `price_history` only receives a row when the price for a
--    (product, store, offer_type) actually changes.
--  * `search_events` / `search_trends` contain no user identifiers: only the
--    normalised term, the postal code, an aggregate count and a timestamp.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    key        TEXT NOT NULL UNIQUE,
    ean        TEXT,
    name       TEXT NOT NULL,
    brand      TEXT,
    category   TEXT,
    unit       TEXT NOT NULL DEFAULT 'stueck',
    quantity   REAL NOT NULL DEFAULT 1.0,
    image_url  TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_products_ean  ON products(ean);
CREATE INDEX IF NOT EXISTS idx_products_name ON products(name);

CREATE TABLE IF NOT EXISTS price_points (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id   INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    store        TEXT NOT NULL,
    offer_type   TEXT NOT NULL DEFAULT 'prospect',
    source       TEXT NOT NULL DEFAULT 'unknown',
    offer_id     TEXT,
    price        REAL NOT NULL,
    old_price    REAL,
    unit_price   REAL,
    unit         TEXT,
    quantity     REAL,
    currency     TEXT NOT NULL DEFAULT 'EUR',
    valid_from   TEXT NOT NULL DEFAULT '',
    valid_to     TEXT NOT NULL DEFAULT '',
    leaflet_url  TEXT,
    observed_at  TEXT NOT NULL,
    observed_day TEXT NOT NULL,
    UNIQUE (product_id, store, offer_type, price, observed_day, valid_from)
);

CREATE INDEX IF NOT EXISTS idx_points_product ON price_points(product_id, store);
CREATE INDEX IF NOT EXISTS idx_points_day     ON price_points(observed_day);

CREATE TABLE IF NOT EXISTS price_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    store      TEXT NOT NULL,
    offer_type TEXT NOT NULL,
    source     TEXT NOT NULL DEFAULT 'unknown',
    price      REAL NOT NULL,
    unit_price REAL,
    changed_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_history_product ON price_history(product_id, store, changed_at);

CREATE TABLE IF NOT EXISTS search_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    query        TEXT NOT NULL,
    postal_code  TEXT,
    result_count INTEGER NOT NULL DEFAULT 0,
    stores       TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    created_day  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_day  ON search_events(created_day);
CREATE INDEX IF NOT EXISTS idx_events_text ON search_events(query);

CREATE TABLE IF NOT EXISTS search_trends (
    day           TEXT NOT NULL,
    query         TEXT NOT NULL,
    postal_code   TEXT NOT NULL DEFAULT '',
    searches      INTEGER NOT NULL DEFAULT 0,
    results       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, query, postal_code)
);

-- ---------------------------------------------------------------------------
-- Community crowdsourcing (anonymous, no accounts)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS community_prices (
    id            TEXT PRIMARY KEY,
    identity      TEXT NOT NULL,
    ean           TEXT,
    name          TEXT NOT NULL,
    store         TEXT NOT NULL,
    price         REAL NOT NULL,
    unit          TEXT,
    quantity      REAL,
    unit_price    REAL,
    postal_code   TEXT NOT NULL,
    scout_id      TEXT,
    source        TEXT NOT NULL DEFAULT 'manual',
    receipt_id    TEXT,
    status        TEXT NOT NULL DEFAULT 'pending',
    confirmations INTEGER NOT NULL DEFAULT 1,
    review_reason TEXT,
    reviewed_at   TEXT,
    reviewed_by   TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_community_lookup
    ON community_prices(identity, store, postal_code, status);
CREATE INDEX IF NOT EXISTS idx_community_plz
    ON community_prices(postal_code, created_at);
CREATE INDEX IF NOT EXISTS idx_community_scout
    ON community_prices(scout_id);

CREATE TABLE IF NOT EXISTS community_confirmations (
    price_id   TEXT NOT NULL REFERENCES community_prices(id) ON DELETE CASCADE,
    scout_id   TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (price_id, scout_id)
);

CREATE TABLE IF NOT EXISTS receipts (
    id           TEXT PRIMARY KEY,
    store        TEXT,
    postal_code  TEXT,
    scout_id     TEXT,
    filename     TEXT,
    content_type TEXT,
    raw_text     TEXT,
    item_count   INTEGER NOT NULL DEFAULT 0,
    engine       TEXT NOT NULL DEFAULT 'text',
    status       TEXT NOT NULL DEFAULT 'parsed',
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_receipts_scout ON receipts(scout_id);


-- ---------------------------------------------------------------------------
-- Weekly harvester runs
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS harvest_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    status       TEXT NOT NULL DEFAULT 'running',
    zips         TEXT NOT NULL DEFAULT '',
    terms        INTEGER NOT NULL DEFAULT 0,
    products     INTEGER NOT NULL DEFAULT 0,
    price_points INTEGER NOT NULL DEFAULT 0,
    price_changes INTEGER NOT NULL DEFAULT 0,
    errors       TEXT NOT NULL DEFAULT '',
    trigger      TEXT NOT NULL DEFAULT 'schedule'
);

CREATE INDEX IF NOT EXISTS idx_harvest_started ON harvest_runs(started_at);

-- ---------------------------------------------------------------------------
-- V1.0: personal receipts (guest mode via owner_token, DSGVO-friendly)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS user_receipts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_token         TEXT NOT NULL,
    store               TEXT NOT NULL,
    postal_code         TEXT,
    country_code        TEXT NOT NULL DEFAULT 'DE',
    currency            TEXT NOT NULL DEFAULT 'EUR',
    receipt_date        TEXT NOT NULL,
    total_cents         INTEGER NOT NULL DEFAULT 0,
    shared_to_community INTEGER NOT NULL DEFAULT 0,
    is_business         INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_user_receipts_owner ON user_receipts(owner_token, receipt_date);

CREATE TABLE IF NOT EXISTS user_receipt_items (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_id       INTEGER NOT NULL REFERENCES user_receipts(id) ON DELETE CASCADE,
    raw_text         TEXT NOT NULL,
    normalized_name  TEXT,
    brand            TEXT,
    category         TEXT,
    quantity         REAL,
    unit             TEXT,
    unit_price_cents INTEGER,
    price_cents      INTEGER NOT NULL,
    discount_cents   INTEGER NOT NULL DEFAULT 0,
    deposit_cents    INTEGER NOT NULL DEFAULT 0,
    vat_rate         REAL,
    is_private       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_user_receipt_items_receipt ON user_receipt_items(receipt_id);

-- ---------------------------------------------------------------------------
-- V1.0: self-learning product aliases (store-specific receipt abbreviations)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS receipt_aliases (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    store            TEXT NOT NULL,
    raw_text_norm    TEXT NOT NULL,
    normalized_name  TEXT NOT NULL,
    brand            TEXT,
    category         TEXT,
    quantity         REAL,
    unit             TEXT,
    hit_count        INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    UNIQUE (store, raw_text_norm)
);
CREATE INDEX IF NOT EXISTS idx_receipt_aliases_lookup ON receipt_aliases(store, raw_text_norm);
