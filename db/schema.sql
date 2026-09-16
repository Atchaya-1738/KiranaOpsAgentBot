PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ============ Inventory ============
CREATE TABLE IF NOT EXISTS products (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    brand           TEXT,
    category        TEXT,
    unit            TEXT NOT NULL CHECK(unit IN ('kg','g','l','ml','packet','dozen','piece')),
    is_loose        INTEGER NOT NULL DEFAULT 0,
    hsn_code        TEXT,
    gst_rate        REAL NOT NULL DEFAULT 0,      -- e.g. 5, 12, 18 (percent, full slab)
    cost_price      REAL NOT NULL DEFAULT 0,
    mrp             REAL NOT NULL DEFAULT 0,
    sell_price      REAL NOT NULL DEFAULT 0,
    qty_on_hand     REAL NOT NULL DEFAULT 0,
    reorder_level   REAL NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_products_name_brand ON products(name, brand);

CREATE TABLE IF NOT EXISTS stock_movements (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id      INTEGER NOT NULL REFERENCES products(id),
    change_qty      REAL NOT NULL,                -- positive = in, negative = out
    movement_type   TEXT NOT NULL CHECK(movement_type IN ('in','out','adjustment')),
    ref_type        TEXT,                          -- 'purchase' | 'bill' | 'initial_stock' | 'adjustment'
    ref_id          INTEGER,
    unit_cost       REAL,
    note            TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============ Billing ============
CREATE TABLE IF NOT EXISTS bills (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    status          TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','finalized','cancelled')),
    customer_name   TEXT,
    payment_mode    TEXT CHECK(payment_mode IN ('cash','upi','card','credit')),
    payment_ref     TEXT,
    subtotal        REAL NOT NULL DEFAULT 0,
    cgst_total      REAL NOT NULL DEFAULT 0,
    sgst_total      REAL NOT NULL DEFAULT 0,
    round_off       REAL NOT NULL DEFAULT 0,
    total           REAL NOT NULL DEFAULT 0,
    idempotency_key TEXT UNIQUE,                  -- guards double-finalize on retried updates
    chat_id         TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    finalized_at    TEXT
);

CREATE TABLE IF NOT EXISTS bill_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_id         INTEGER NOT NULL REFERENCES bills(id),
    product_id      INTEGER NOT NULL REFERENCES products(id),
    product_name    TEXT NOT NULL,
    qty             REAL NOT NULL,
    unit            TEXT NOT NULL,
    unit_price      REAL NOT NULL,
    gst_rate        REAL NOT NULL,
    taxable_value   REAL NOT NULL,
    cgst_amt        REAL NOT NULL,
    sgst_amt        REAL NOT NULL,
    line_total      REAL NOT NULL,
    hsn_code        TEXT
);

-- ============ Khata (credit ledger) ============
CREATE TABLE IF NOT EXISTS khata_customers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,
    phone           TEXT,
    balance         REAL NOT NULL DEFAULT 0,       -- positive = customer owes the shop
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS khata_transactions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id     INTEGER NOT NULL REFERENCES khata_customers(id),
    type            TEXT NOT NULL CHECK(type IN ('credit','payment')),
    amount          REAL NOT NULL,
    ref_bill_id     INTEGER,
    note            TEXT,
    idempotency_key TEXT UNIQUE,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============ Long-term memory (survives /new, survives restarts) ============
CREATE TABLE IF NOT EXISTS preferences (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============ Idempotency plumbing ============
CREATE TABLE IF NOT EXISTS telegram_updates_seen (
    update_id   INTEGER PRIMARY KEY,
    chat_id     TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============ Per-chat session state (short-term, not conversational memory) ============
CREATE TABLE IF NOT EXISTS chat_sessions (
    chat_id         TEXT PRIMARY KEY,
    draft_bill_id   INTEGER,
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS conversation_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     TEXT NOT NULL,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,      -- plain text (compacted; see agent/orchestrator.py)
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
