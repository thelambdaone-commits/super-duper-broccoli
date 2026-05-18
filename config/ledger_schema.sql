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
    requested_qty REAL DEFAULT 0.0,
    filled_qty REAL DEFAULT 0.0,
    execution_price REAL DEFAULT 0.0,
    notional_usd REAL DEFAULT 0.0,
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
    requested_qty REAL DEFAULT 0.0,
    filled_qty REAL DEFAULT 0.0,
    execution_price REAL DEFAULT 0.0,
    notional_usd REAL DEFAULT 0.0,
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
    closed_at TIMESTAMP,
    exit_price REAL,
    pnl REAL,
    is_win INTEGER,
    mid_price_signal REAL,
    fill_price REAL,
    slippage REAL,
    execution_mode TEXT DEFAULT 'PAPER'
);

-- Active trades for resolution tracking
CREATE TABLE IF NOT EXISTS active_trades (
    trade_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    condition_id TEXT NOT NULL,
    side TEXT NOT NULL,
    entry_price REAL NOT NULL,
    size REAL NOT NULL,
    capital_engaged REAL NOT NULL,
    mid_price_at_signal REAL NOT NULL,
    fill_price REAL NOT NULL,
    friction_cost REAL DEFAULT 0.0,
    confidence REAL NOT NULL,
    signal_source TEXT NOT NULL,
    regime_label TEXT DEFAULT '',
    resolution_timestamp REAL NOT NULL,
    status TEXT DEFAULT 'OPEN',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Historical performance for post-mortem analysis
CREATE TABLE IF NOT EXISTS historical_performance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id TEXT NOT NULL UNIQUE,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL NOT NULL,
    size REAL NOT NULL,
    capital_engaged REAL NOT NULL,
    gross_pnl REAL NOT NULL,
    friction_cost REAL NOT NULL,
    net_pnl REAL NOT NULL,
    is_win INTEGER NOT NULL,
    mid_price_at_signal REAL NOT NULL,
    fill_price REAL NOT NULL,
    slippage REAL NOT NULL,
    execution_loss_pct REAL NOT NULL,
    model_error REAL,
    alpha_source TEXT NOT NULL,
    confidence REAL NOT NULL,
    regime_label TEXT DEFAULT '',
    resolution_time TIMESTAMP NOT NULL,
    settled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Performance metrics (rolling, one row per execution mode)
CREATE TABLE IF NOT EXISTS performance_metrics (
    execution_mode TEXT PRIMARY KEY NOT NULL DEFAULT 'PAPER',
    total_trades INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,
    losing_trades INTEGER DEFAULT 0,
    total_gross_pnl REAL DEFAULT 0.0,
    total_net_pnl REAL DEFAULT 0.0,
    total_friction REAL DEFAULT 0.0,
    win_rate REAL DEFAULT 0.0,
    profit_factor REAL DEFAULT 0.0,
    max_drawdown REAL DEFAULT 0.0,
    avg_win REAL DEFAULT 0.0,
    avg_loss REAL DEFAULT 0.0,
    execution_loss_rate REAL DEFAULT 0.0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Execution mode configuration
CREATE TABLE IF NOT EXISTS execution_config (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    mode TEXT NOT NULL DEFAULT 'PAPER',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Safety flags for execution restrictions
CREATE TABLE IF NOT EXISTS safety_flags (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    strict_maker_only INTEGER DEFAULT 0,
    max_kelly_pct REAL DEFAULT 0.25,
    triggered_at TIMESTAMP,
    reason TEXT
);

INSERT INTO capital_allocation (total_capital, allocated_pct, available_capital)
SELECT 10000.0, 5.0, 10000.0
WHERE NOT EXISTS (SELECT 1 FROM capital_allocation);

INSERT INTO execution_config (id, mode)
SELECT 1, 'PAPER'
WHERE NOT EXISTS (SELECT 1 FROM execution_config);

INSERT OR IGNORE INTO performance_metrics (execution_mode) VALUES ('PAPER');
INSERT OR IGNORE INTO performance_metrics (execution_mode) VALUES ('SHADOW');
INSERT OR IGNORE INTO performance_metrics (execution_mode) VALUES ('PROD');

INSERT INTO safety_flags (id, strict_maker_only, max_kelly_pct)
SELECT 1, 0, 0.25
WHERE NOT EXISTS (SELECT 1 FROM safety_flags);
