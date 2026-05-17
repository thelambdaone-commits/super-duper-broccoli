import logging
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

from config.constants import EXECUTION_MODES
from utils.exceptions import QuantFatal

logger = logging.getLogger("Ledger")

DEFAULT_DATA_DIR = os.getenv("DATA_PATH", ".")
LEDGER_DB_PATH = os.path.join(DEFAULT_DATA_DIR, "ledger.db")
SCHEMA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "config", "ledger_schema.sql"
)


class Ledger:
    def __init__(self, db_path: str = LEDGER_DB_PATH, schema_path: str = SCHEMA_PATH) -> None:
        self.db_path = db_path
        self.schema_path = schema_path
        self._conn = self._open_connection()
        self._initialize_database()

    def _open_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    def _initialize_database(self) -> None:
        if not os.path.exists(self.schema_path):
            raise QuantFatal(f"Schema not found: {self.schema_path}")
        with open(self.schema_path) as f:
            self._conn.executescript(f.read())
        self._conn.commit()
        
        # Upgrade existing databases with new columns safely
        for col, col_type in [("exit_price", "REAL"), ("pnl", "REAL"), ("is_win", "INTEGER"), ("tenant_wallet", "TEXT")]:
            try:
                self._conn.execute(f"ALTER TABLE paper_positions ADD COLUMN {col} {col_type}")
            except sqlite3.OperationalError:
                pass

        try:
            self._conn.execute("ALTER TABLE positions ADD COLUMN tenant_wallet TEXT")
        except sqlite3.OperationalError:
            pass

        self._conn.commit()
        logger.info("Ledger schema initialized")

    @contextmanager
    def _transaction(self):
        cursor = self.conn.cursor()
        try:
            cursor.execute("BEGIN IMMEDIATE")
            yield cursor
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def validate_and_reserve(
        self, ticker: str, side: str, limit_price: float, requested_size: float
    ) -> Dict[str, Any]:
        if limit_price <= 0 or requested_size <= 0:
            return {"authorized": False, "reason": "Invalid non-positive price or size."}
        capital_required = limit_price * requested_size

        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT total_capital, allocated_pct, available_capital "
            "FROM capital_allocation ORDER BY id DESC LIMIT 1"
        )
        allocation = cursor.fetchone()

        if not allocation:
            return {"authorized": False, "reason": "No allocation config found."}

        total_capital = allocation["total_capital"]
        max_pct = allocation["allocated_pct"]
        available = allocation["available_capital"]

        hard_cap = total_capital * (max_pct / 100.0)

        if capital_required > available:
            return {
                "authorized": False,
                "reason": f"Insufficient capital. Required: {capital_required}, Available: {available}",
            }

        if capital_required > hard_cap:
            adjusted_size = hard_cap / limit_price
            adjusted_capital = limit_price * adjusted_size
            logger.info(
                f"Circuit breaker adjusted size ({max_pct}%% max): "
                f"{requested_size} -> {adjusted_size}"
            )
            return {
                "authorized": True,
                "size": adjusted_size,
                "capital": adjusted_capital,
                "reason": "Size adjusted by hardware circuit breaker.",
            }

        return {
            "authorized": True,
            "size": requested_size,
            "capital": capital_required,
            "reason": "Nominal validation passed.",
        }

    def record_order(
        self, position_id: str, ticker: str, side: str, price: float, size: float, tenant_wallet: Optional[str] = None
    ) -> None:
        if price <= 0 or size <= 0:
            raise QuantFatal("Order persistence failed: price and size must be positive")
        capital_engaged = price * size

        try:
            with self._transaction() as cursor:
                cursor.execute(
                    "SELECT available_capital FROM capital_allocation ORDER BY id DESC LIMIT 1"
                )
                allocation = cursor.fetchone()
                if not allocation:
                    raise QuantFatal("No allocation config found.")
                if capital_engaged > allocation["available_capital"]:
                    raise QuantFatal(
                        f"Insufficient capital during reservation. Required: {capital_engaged}, "
                        f"Available: {allocation['available_capital']}"
                    )

                cursor.execute(
                    "SELECT size, capital_engaged FROM positions "
                    "WHERE position_id = ? AND status = 'OPEN'",
                    (position_id,),
                )
                existing = cursor.fetchone()

                if existing:
                    new_size = existing["size"] + size
                    new_capital = existing["capital_engaged"] + capital_engaged
                    cursor.execute(
                        "UPDATE positions SET size = ?, capital_engaged = ? WHERE position_id = ?",
                        (new_size, new_capital, position_id),
                    )
                else:
                    cursor.execute(
                        "INSERT INTO positions (position_id, ticker, side, entry_price, size, capital_engaged, tenant_wallet) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (position_id, ticker, side, price, size, capital_engaged, tenant_wallet),
                    )

                cursor.execute(
                    "INSERT INTO transactions (position_id, ticker, side, price, size) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (position_id, ticker, side, price, size),
                )

                cursor.execute(
                    "UPDATE capital_allocation SET available_capital = available_capital - ? "
                    "WHERE id = (SELECT max(id) FROM capital_allocation)",
                    (capital_engaged,),
                )
                if cursor.rowcount != 1:
                    raise QuantFatal("Capital reservation update failed.")
            logger.info(
                f"Position {position_id} updated. "
                f"{capital_engaged} deducted from available capital."
            )

        except (sqlite3.Error, QuantFatal) as e:
            raise QuantFatal(f"Order persistence failed: {e}")

    def get_capital_summary(self) -> dict:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM capital_allocation ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        return dict(row) if row else {}

    def get_open_positions(self) -> list[dict]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM positions WHERE status = 'OPEN'")
        return [dict(row) for row in cursor.fetchall()]

    def get_execution_mode(self) -> str:
        cursor = self.conn.cursor()
        cursor.execute("SELECT mode FROM execution_config WHERE id = 1")
        row = cursor.fetchone()
        return row["mode"] if row else "PAPER"

    def set_execution_mode(self, mode: str) -> None:
        mode_upper = mode.upper().strip()
        if mode_upper not in EXECUTION_MODES:
            raise ValueError(f"Invalid execution mode: {mode}. Choose from {EXECUTION_MODES}")
        with self._transaction() as cursor:
            cursor.execute(
                "INSERT OR REPLACE INTO execution_config (id, mode, updated_at) "
                "VALUES (1, ?, CURRENT_TIMESTAMP)",
                (mode_upper,),
            )
        logger.info(f"Execution mode set to: {mode_upper}")

    def record_paper_order(
        self,
        ticker: str,
        side: str,
        price: float,
        size: float,
        confidence: float = 0.0,
        regime_label: str = "",
        signal_source: str = "",
        tenant_wallet: Optional[str] = None,
    ) -> dict:
        if price <= 0 or size <= 0:
            return {"error": "price and size must be positive"}
        capital_virtual = price * size
        position_id = f"paper-{ticker}-{side}-{int(time.time())}-{uuid.uuid4().hex[:6]}"
        try:
            with self._transaction() as cursor:
                cursor.execute(
                    "INSERT INTO paper_positions "
                    "(position_id, ticker, side, entry_price, size, capital_virtual, "
                    "confidence, regime_label, signal_source, tenant_wallet) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (position_id, ticker, side, price, size, capital_virtual,
                     confidence, regime_label, signal_source, tenant_wallet),
                )

            logger.info(f"Paper order recorded: {side} {size} {ticker} @ {price}")
            return {
                "position_id": position_id,
                "ticker": ticker,
                "side": side,
                "size": size,
                "capital_virtual": capital_virtual,
            }
        except sqlite3.Error as e:
            logger.error(f"Paper order failed: {e}")
            return {"error": str(e)}

    def get_paper_positions(self, status: str = "OPEN") -> list[dict]:
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM paper_positions WHERE status = ? ORDER BY opened_at DESC",
            (status,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def close_paper_position(
        self, position_id: str, exit_price: Optional[float] = None, pnl: Optional[float] = None, is_win: Optional[bool] = None
    ) -> None:
        cursor = self.conn.cursor()
        if exit_price is not None:
            is_win_val = int(is_win) if is_win is not None else None
            cursor.execute(
                "UPDATE paper_positions SET status = 'CLOSED', closed_at = CURRENT_TIMESTAMP, "
                "exit_price = ?, pnl = ?, is_win = ? "
                "WHERE position_id = ?",
                (exit_price, pnl, is_win_val, position_id),
            )
        else:
            cursor.execute(
                "UPDATE paper_positions SET status = 'CLOSED', closed_at = CURRENT_TIMESTAMP "
                "WHERE position_id = ?",
                (position_id,),
            )
        self.conn.commit()

    def close_position(self, position_id: str) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE positions SET status = 'CLOSED' WHERE position_id = ?",
            (position_id,),
        )
        self.conn.commit()

    def get_active_trades(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM active_trades WHERE status = 'OPEN'")
        return cursor.fetchall()

    def get_performance_summary(self, mode: str = "PAPER") -> Dict[str, Any]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM performance_metrics WHERE execution_mode = ?", (mode,))
        row = cursor.fetchone()
        if not row:
            return {}
        return dict(row)

    def get_safety_flags(self) -> Dict[str, Any]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM safety_flags WHERE id = 1")
        row = cursor.fetchone()
        if not row:
            return {}
        return dict(row)

    def set_safety_flag(self, strict_maker_only: bool, max_kelly_pct: float, reason: str) -> None:
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE safety_flags SET
                strict_maker_only = ?,
                max_kelly_pct = ?,
                triggered_at = CURRENT_TIMESTAMP,
                reason = ?
            WHERE id = 1
        """, (int(strict_maker_only), max_kelly_pct, reason))
        self.conn.commit()

    def get_historical_performance(self, limit: int = 50) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM historical_performance
            ORDER BY settled_at DESC LIMIT ?
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]
