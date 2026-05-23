import logging
import os
import sqlite3

from utils.exceptions import QuantFatal

logger = logging.getLogger("Ledger.Schema")


def initialize_database(conn: sqlite3.Connection, schema_path: str) -> None:
    if not os.path.exists(schema_path):
        raise QuantFatal(f"Schema not found: {schema_path}")
    with open(schema_path) as f:
        conn.executescript(f.read())
    conn.commit()
    migrate_schema(conn)

    for col, col_type in [
        ("exit_price", "REAL"),
        ("pnl", "REAL"),
        ("is_win", "INTEGER"),
        ("tenant_wallet", "TEXT"),
        ("stop_loss_pct", "REAL DEFAULT 0.0"),
        ("stop_loss_cents", "REAL DEFAULT 0.0"),
        ("take_profit_pct", "REAL DEFAULT 0.0"),
    ]:
        try:
            conn.execute(f"ALTER TABLE paper_positions ADD COLUMN {col} {col_type}")
        except sqlite3.OperationalError:
            pass

    for col, col_type in [
        ("tenant_wallet", "TEXT"),
        ("is_win", "INTEGER"),
        ("signal_source", "TEXT DEFAULT ''"),
    ]:
        try:
            conn.execute(f"ALTER TABLE positions ADD COLUMN {col} {col_type}")
        except sqlite3.OperationalError:
            pass

    migrate_performance_metrics(conn)
    seed_performance_metrics_modes(conn)
    ensure_execution_columns(conn)
    conn.commit()
    logger.info("Ledger schema initialized")


def migrate_schema(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()
    for col in ("stop_loss_pct", "take_profit_pct", "exit_price", "pnl", "closed_at"):
        try:
            cursor.execute(f"ALTER TABLE positions ADD COLUMN {col} REAL")
        except sqlite3.OperationalError:
            pass
    conn.commit()


def migrate_performance_metrics(conn: sqlite3.Connection) -> None:
    cursor = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='performance_metrics'"
    )
    row = cursor.fetchone()
    if row and 'CHECK' in row[0].upper():
        logger.info("Migrating performance_metrics table to multi-mode schema")
        conn.execute("DROP TABLE performance_metrics")


def seed_performance_metrics_modes(conn: sqlite3.Connection) -> None:
    for mode in ('PAPER', 'SHADOW', 'PROD'):
        try:
            conn.execute(
                "INSERT OR IGNORE INTO performance_metrics (execution_mode) VALUES (?)",
                (mode,),
            )
        except Exception:
            pass


def ensure_execution_columns(conn: sqlite3.Connection) -> None:
    for table in ("positions", "transactions"):
        for col, col_type in [
            ("requested_qty", "REAL"),
            ("filled_qty", "REAL"),
            ("execution_price", "REAL"),
            ("notional_usd", "REAL"),
        ]:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type} DEFAULT 0.0")
            except sqlite3.OperationalError:
                pass
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN exchange_order_id TEXT")
        except sqlite3.OperationalError:
            pass
