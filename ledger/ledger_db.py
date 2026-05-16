import logging
import os
import sqlite3
import time
from typing import Any, Dict, Optional

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
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
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

    def validate_and_reserve(
        self, ticker: str, side: str, limit_price: float, requested_size: float
    ) -> Dict[str, Any]:
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
        self, position_id: str, ticker: str, side: str, price: float, size: float
    ) -> None:
        capital_engaged = price * size

        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "INSERT INTO transactions (position_id, ticker, side, price, size) "
                "VALUES (?, ?, ?, ?, ?)",
                (position_id, ticker, side, price, size),
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
                    "INSERT INTO positions (position_id, ticker, side, entry_price, size, capital_engaged) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (position_id, ticker, side, price, size, capital_engaged),
                )

            cursor.execute(
                "UPDATE capital_allocation SET available_capital = available_capital - ? "
                "WHERE id = (SELECT max(id) FROM capital_allocation)",
                (capital_engaged,),
            )

            self.conn.commit()
            logger.info(
                f"Position {position_id} updated. "
                f"{capital_engaged} deducted from available capital."
            )

        except sqlite3.Error as e:
            self.conn.rollback()
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
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO execution_config (id, mode, updated_at) "
            "VALUES (1, ?, CURRENT_TIMESTAMP)",
            (mode_upper,),
        )
        self.conn.commit()
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
    ) -> dict:
        capital_virtual = price * size
        position_id = f"paper-{ticker}-{side}-{int(time.time())}"
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "INSERT INTO paper_positions "
                "(position_id, ticker, side, entry_price, size, capital_virtual, "
                "confidence, regime_label, signal_source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (position_id, ticker, side, price, size, capital_virtual,
                 confidence, regime_label, signal_source),
            )
            self.conn.commit()
            logger.info(f"Paper order recorded: {side} {size} {ticker} @ {price}")
            return {
                "position_id": position_id,
                "ticker": ticker,
                "side": side,
                "size": size,
                "capital_virtual": capital_virtual,
            }
        except sqlite3.Error as e:
            self.conn.rollback()
            logger.error(f"Paper order failed: {e}")
            return {"error": str(e)}

    def get_paper_positions(self, status: str = "OPEN") -> list[dict]:
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM paper_positions WHERE status = ? ORDER BY opened_at DESC",
            (status,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def close_paper_position(self, position_id: str) -> None:
        cursor = self.conn.cursor()
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
