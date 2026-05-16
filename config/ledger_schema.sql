-- DDL pour persistance d'état financière stricte (Anti-Agent Crash)

CREATE TABLE IF NOT EXISTS capital_allocation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    total_capital REAL NOT NULL,
    allocated_pct REAL NOT NULL,
    available_capital REAL NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS positions (
    position_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    entry_price REAL NOT NULL,
    size REAL NOT NULL,
    capital_engaged REAL NOT NULL,
    status TEXT DEFAULT 'OPEN',
    opened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS transactions (
    tx_id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id TEXT,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    price REAL NOT NULL,
    size REAL NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(position_id) REFERENCES positions(position_id)
);

-- Paper trading positions (simulated, no real capital)
CREATE TABLE IF NOT EXISTS paper_positions (
    position_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    entry_price REAL NOT NULL,
    size REAL NOT NULL,
    capital_virtual REAL NOT NULL,
    status TEXT DEFAULT 'OPEN',
    confidence REAL DEFAULT 0.0,
    regime_label TEXT DEFAULT '',
    signal_source TEXT DEFAULT '',
    opened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    closed_at TIMESTAMP
);

-- Execution mode configuration
CREATE TABLE IF NOT EXISTS execution_config (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    mode TEXT NOT NULL DEFAULT 'PAPER',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO capital_allocation (total_capital, allocated_pct, available_capital)
SELECT 10000.0, 5.0, 10000.0
WHERE NOT EXISTS (SELECT 1 FROM capital_allocation);

INSERT INTO execution_config (id, mode)
SELECT 1, 'PAPER'
WHERE NOT EXISTS (SELECT 1 FROM execution_config);
