import logging
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

from config.constants import EXECUTION_MODES
from utils.config_loader import get_trading_config
from utils.exceptions import QuantFatal

from ledger.schema import initialize_database as _init_schema

logger = logging.getLogger("Ledger")

DEFAULT_DATA_DIR = os.getenv("DATA_PATH", "data")
LEDGER_DB_PATH = os.path.join(DEFAULT_DATA_DIR, "ledger.db")
SCHEMA_PATH = os.path.join(
    os.getenv(
        "CONFIG_PATH",
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "configs", "config"),
    ),
    "ledger_schema.sql",
)


class Ledger:
    def __init__(self, db_path: str = LEDGER_DB_PATH, schema_path: str = SCHEMA_PATH) -> None:
        self.db_path = db_path
        self.schema_path = schema_path
        self._lock = threading.RLock()
        self._conn = self._open_connection()
        self._initialize_database()

    def _open_connection(self) -> sqlite3.Connection:
        # FastAPI runs sync handlers in a worker thread pool; the shared ledger
        # connection must be usable from those threads and serialized by _lock.
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
        _init_schema(self._conn, self.schema_path)
        self._ensure_execution_config_columns()

    @contextmanager
    def _transaction(self):
        with self._lock:
            cursor = self.conn.cursor()
            try:
                cursor.execute("BEGIN IMMEDIATE")
                yield cursor
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    def validate_and_reserve(
        self,
        ticker: str,
        side: str,
        limit_price: float,
        requested_size: float,
        fee_rate_bps: Optional[float] = None,
    ) -> Dict[str, Any]:
        if limit_price <= 0 or requested_size <= 0:
            return {"authorized": False, "reason": "Invalid non-positive price or size."}
        mode = self.get_execution_mode()
        fee_rate_bps = self._effective_fee_rate_bps(mode, fee_rate_bps)
        notional = limit_price * requested_size
        fee_buffer = notional * (fee_rate_bps / 10_000.0)
        capital_required = notional + fee_buffer

        with self._lock:
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
                "fee_rate_bps": fee_rate_bps,
                "estimated_fee": adjusted_capital * (fee_rate_bps / 10_000.0),
            }

        return {
            "authorized": True,
            "size": requested_size,
            "capital": capital_required,
            "reason": "Nominal validation passed.",
            "fee_rate_bps": fee_rate_bps,
            "estimated_fee": fee_buffer,
        }

    def record_order(
        self,
        position_id: str,
        ticker: str,
        side: str,
        price: float,
        size: float,
        tenant_wallet: Optional[str] = None,
        requested_qty: Optional[float] = None,
        filled_qty: Optional[float] = None,
        execution_price: Optional[float] = None,
        notional_usd: Optional[float] = None,
        exchange_order_id: Optional[str] = None,
        fee_rate_bps: Optional[float] = None,
    ) -> None:
        if price <= 0 or size <= 0:
            raise QuantFatal("Order persistence failed: price and size must be positive")
        filled_qty_val = float(filled_qty if filled_qty is not None else size)
        execution_price_val = float(execution_price if execution_price is not None else price)
        requested_qty_val = float(requested_qty if requested_qty is not None else size)
        notional_usd_val = float(notional_usd if notional_usd is not None else execution_price_val * filled_qty_val)
        mode = self.get_execution_mode()
        fee_rate_bps = self._effective_fee_rate_bps(mode, fee_rate_bps)
        fee_amount = notional_usd_val * (fee_rate_bps / 10_000.0)
        capital_engaged = notional_usd_val + fee_amount

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
                        "UPDATE positions SET size = ?, capital_engaged = ?, requested_qty = requested_qty + ?, "
                        "filled_qty = filled_qty + ?, execution_price = ?, notional_usd = notional_usd + ?, exchange_order_id = ? "
                        "WHERE position_id = ?",
                        (
                            new_size,
                            new_capital,
                            requested_qty_val,
                            filled_qty_val,
                            execution_price_val,
                            notional_usd_val,
                            exchange_order_id,
                            position_id,
                        ),
                    )
                else:
                    cursor.execute(
                        "INSERT INTO positions (position_id, ticker, side, entry_price, size, requested_qty, filled_qty, execution_price, notional_usd, capital_engaged, tenant_wallet, exchange_order_id) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            position_id,
                            ticker,
                            side,
                            price,
                            size,
                            requested_qty_val,
                            filled_qty_val,
                            execution_price_val,
                            notional_usd_val,
                            capital_engaged,
                            tenant_wallet,
                            exchange_order_id,
                        ),
                    )

                cursor.execute(
                    "INSERT INTO transactions (position_id, ticker, side, price, size, requested_qty, filled_qty, execution_price, notional_usd, exchange_order_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        position_id,
                        ticker,
                        side,
                        price,
                        size,
                        requested_qty_val,
                        filled_qty_val,
                        execution_price_val,
                        notional_usd_val,
                        exchange_order_id,
                    ),
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
                f"{capital_engaged} deducted from available capital (including fees)."
            )

        except (sqlite3.Error, QuantFatal) as e:
            raise QuantFatal(f"Order persistence failed: {e}")

    def get_capital_summary(self) -> dict:
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM capital_allocation ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            return dict(row) if row else {}

    def sync_capital(self, real_total_capital: float) -> None:
        """Updates the ledger with the real-world capital from the blockchain."""
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT allocated_pct "
                "FROM capital_allocation ORDER BY id DESC LIMIT 1"
            )
            allocation = cursor.fetchone()
            cursor.execute(
                "SELECT COALESCE(SUM(capital_engaged), 0.0) AS engaged_capital "
                "FROM positions WHERE status = 'OPEN'"
            )
            engaged_row = cursor.fetchone()
            engaged = float(engaged_row["engaged_capital"] or 0.0) if engaged_row else 0.0
            new_available = max(0.0, real_total_capital - engaged)

            if not allocation:
                # Default if none exists: 5% allocation limit
                cursor.execute(
                    "INSERT INTO capital_allocation (total_capital, allocated_pct, available_capital) "
                    "VALUES (?, ?, ?)",
                    (real_total_capital, 5.0, new_available)
                )
            else:
                cursor.execute(
                    "INSERT INTO capital_allocation (total_capital, allocated_pct, available_capital) "
                    "VALUES (?, ?, ?)",
                    (real_total_capital, allocation["allocated_pct"], new_available)
                )
            self.conn.commit()
            logger.info(f"Capital synced with real balance: {real_total_capital:.2f} $")

    def get_open_positions(self) -> list[dict]:
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM positions WHERE status = 'OPEN'")
            return [dict(row) for row in cursor.fetchall()]

    def _ensure_execution_config_columns(self) -> None:
        for col, col_type in [
            ("is_manual_override", "INTEGER DEFAULT 0"),
        ]:
            try:
                self._conn.execute(f"ALTER TABLE execution_config ADD COLUMN {col} {col_type}")
            except sqlite3.OperationalError:
                pass

    def get_execution_mode(self) -> str:
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT mode FROM execution_config WHERE id = 1")
            row = cursor.fetchone()
            return row["mode"] if row else "PAPER"

    def is_manual_mode(self) -> bool:
        with self._lock:
            cursor = self.conn.cursor()
            try:
                cursor.execute("SELECT is_manual_override FROM execution_config WHERE id = 1")
                row = cursor.fetchone()
                return bool(row["is_manual_override"]) if row else False
            except (sqlite3.OperationalError, KeyError):
                return False

    def set_execution_mode(self, mode: str, manual: bool = False) -> None:
        mode_upper = mode.upper().strip()
        if mode_upper not in EXECUTION_MODES:
            raise ValueError(f"Invalid execution mode: {mode}. Choose from {EXECUTION_MODES}")
        with self._transaction() as cursor:
            cursor.execute(
                "INSERT OR REPLACE INTO execution_config (id, mode, is_manual_override, updated_at) "
                "VALUES (1, ?, ?, CURRENT_TIMESTAMP)",
                (mode_upper, 1 if manual else 0),
            )
        try:
            from core.swarm_supervisor import get_swarm_supervisor

            get_swarm_supervisor().sync_execution_mode(mode_upper)
        except Exception as exc:
            logger.debug("Swarm mode sync skipped: %s", exc)
        logger.info(f"Execution mode set to: {mode_upper} (Manual: {manual})")

    def record_paper_order(
        self,
        ticker: str,
        side: str,
        price: float,
        size: float,
        requested_qty: Optional[float] = None,
        filled_qty: Optional[float] = None,
        execution_price: Optional[float] = None,
        notional_usd: Optional[float] = None,
        confidence: float = 0.0,
        regime_label: str = "",
        signal_source: str = "",
        tenant_wallet: Optional[str] = None,
    ) -> dict:
        if price <= 0 or size <= 0:
            return {"error": "price and size must be positive"}
        requested_qty_val = float(requested_qty if requested_qty is not None else size)
        filled_qty_val = float(filled_qty if filled_qty is not None else size)
        execution_price_val = float(execution_price if execution_price is not None else price)
        notional_usd_val = float(notional_usd if notional_usd is not None else execution_price_val * filled_qty_val)
        capital_virtual = notional_usd_val
        position_id = f"paper-{ticker}-{side}-{int(time.time())}-{uuid.uuid4().hex[:6]}"
        try:
            with self._transaction() as cursor:
                cursor.execute(
                    "INSERT INTO paper_positions "
                    "(position_id, ticker, side, entry_price, size, capital_virtual, "
                    "confidence, regime_label, signal_source, tenant_wallet) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (position_id, ticker, side, price, filled_qty_val, capital_virtual,
                     confidence, regime_label, signal_source, tenant_wallet),
                )

            logger.info(f"Paper order recorded: {side} {filled_qty_val} {ticker} @ {execution_price_val}")
            return {
                "position_id": position_id,
                "ticker": ticker,
                "side": side,
                "requested_qty": requested_qty_val,
                "filled_qty": filled_qty_val,
                "execution_price": execution_price_val,
                "notional_usd": notional_usd_val,
                "size": filled_qty_val,
                "capital_virtual": capital_virtual,
            }
        except sqlite3.Error as e:
            logger.error(f"Paper order failed: {e}")
            return {"error": str(e)}

    def get_paper_positions(self, status: str = "OPEN") -> list[dict]:
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT * FROM paper_positions WHERE status = ? ORDER BY opened_at DESC",
                (status,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def close_paper_position(
        self, position_id: str, exit_price: Optional[float] = None, pnl: Optional[float] = None, is_win: Optional[bool] = None
    ) -> None:
        with self._lock:
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

            if pnl is not None:
                self._update_performance_from_paper(pnl, is_win if is_win is not None else False)

            self.conn.commit()

    def _update_performance_from_paper(self, pnl: float, is_win: bool) -> None:
        with self._lock:
            is_win_int = 1 if is_win else 0
            cursor = self.conn.cursor()

            cursor.execute(
                "INSERT OR IGNORE INTO performance_metrics (execution_mode) VALUES ('PAPER')",
            )

            cursor.execute("""
                SELECT total_trades, winning_trades, losing_trades,
                       total_net_pnl, total_friction, avg_win, avg_loss
                FROM performance_metrics WHERE execution_mode = 'PAPER'
            """)
            metrics = cursor.fetchone()
            if not metrics:
                return

            total_trades = metrics["total_trades"] + 1
            winning_trades = metrics["winning_trades"] + is_win_int
            losing_trades = metrics["losing_trades"] + (0 if is_win else 1)
            total_net_pnl = metrics["total_net_pnl"] + pnl

            win_rate = winning_trades / total_trades if total_trades > 0 else 0.0
            avg_win = (
                (metrics["avg_win"] * metrics["winning_trades"] + (pnl if is_win else 0))
                / winning_trades if winning_trades > 0 else 0.0
            )
            avg_loss = (
                (metrics["avg_loss"] * metrics["losing_trades"] + (pnl if not is_win else 0))
                / losing_trades if losing_trades > 0 else 0.0
            )
            profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else 0.0

            cursor.execute("""
                UPDATE performance_metrics SET
                    total_trades = ?, winning_trades = ?, losing_trades = ?,
                    total_net_pnl = ?, win_rate = ?, profit_factor = ?,
                    avg_win = ?, avg_loss = ?, updated_at = CURRENT_TIMESTAMP
                WHERE execution_mode = 'PAPER'
            """, (total_trades, winning_trades, losing_trades, total_net_pnl,
                  win_rate, profit_factor, avg_win, avg_loss))

    def get_performance_summary_by_source(self, mode: str | None = None) -> Dict[str, Dict[str, float]]:
        """
        Computes performance metrics (total PnL, win rate) grouped by signal source.
        Used by the SignalFusionEngine to adapt weights.

        Args:
            mode: Optional filter ('PAPER' or 'PROD'). If None, returns aggregate.
        """
        with self._lock:
            cursor = self.conn.cursor()

            where_clause = ""
            params = []
            if mode:
                where_clause = "WHERE execution_mode = ?"
                params = [mode]

            query = f"""
                SELECT signal_source, SUM(pnl) as total_pnl,
                       COUNT(*) as total_trades,
                       SUM(CASE WHEN is_win = 1 THEN 1 ELSE 0 END) as wins
                FROM (
                    SELECT signal_source, pnl, is_win, 'PROD' as execution_mode FROM positions WHERE status = 'CLOSED'
                    UNION ALL
                    SELECT signal_source, pnl, is_win, 'PAPER' as execution_mode FROM paper_positions WHERE status = 'CLOSED'
                )
                {where_clause}
                GROUP BY signal_source
            """
            cursor.execute(query, params)
            rows = cursor.fetchall()

            results = {}
            for row in rows:
                source = row["signal_source"]
                if not source: continue

                # Cleanup source ID (strip prefixes like 'autonomous:')
                source_id = source.split(":")[-1] if ":" in source else source

                results[source_id] = {
                    "total_pnl": float(row["total_pnl"] or 0.0),
                    "total_trades": int(row["total_trades"] or 0),
                    "win_rate": (float(row["wins"] or 0) / float(row["total_trades"])) if row["total_trades"] > 0 else 0.0
                }
            return results

    @staticmethod
    def _effective_fee_rate_bps(mode: str, fee_rate_bps: Optional[float]) -> float:
        if fee_rate_bps is not None:
            try:
                return max(0.0, float(fee_rate_bps))
            except (TypeError, ValueError):
                return 0.0
        if mode.upper() in {"PROD", "SHADOW"}:
            raw = os.getenv("ESTIMATED_TRADE_FEE_BPS", str(get_trading_config("estimated_trade_fee_bps", 200)))
            try:
                return max(0.0, float(raw))
            except (TypeError, ValueError):
                return 200.0
        return 0.0

    def update_position_fill(
        self,
        exchange_order_id: str,
        filled_qty: float,
        execution_price: float,
    ) -> bool:
        """Met à jour une position ouverte suite à un fill partiel ou total reçu du WebSocket."""
        try:
            with self._transaction() as cursor:
                # Trouver la position par exchange_order_id
                cursor.execute(
                    "SELECT position_id, ticker, side, entry_price, size, filled_qty FROM positions "
                    "WHERE exchange_order_id = ? AND status = 'OPEN'",
                    (exchange_order_id,),
                )
                pos = cursor.fetchone()
                if not pos:
                    logger.debug(f"Position not found for exchange_order_id: {exchange_order_id}")
                    return False

                position_id = pos["position_id"]
                new_filled_qty = pos["filled_qty"] + filled_qty

                # Update position
                cursor.execute(
                    "UPDATE positions SET filled_qty = ?, execution_price = ? WHERE position_id = ?",
                    (new_filled_qty, execution_price, position_id),
                )

                # Check if fully filled (optional: status update if needed)
                # On Polymarket, one order can have multiple fills.

                # Record transaction
                cursor.execute(
                    "INSERT INTO transactions (position_id, ticker, side, price, size, filled_qty, execution_price, exchange_order_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (position_id, pos["ticker"], pos["side"], pos["entry_price"], filled_qty, filled_qty, execution_price, exchange_order_id),
                )

            logger.info(f"✅ Position {position_id} mise à jour (fill: {filled_qty} @ {execution_price})")
            return True
        except Exception as e:
            logger.error(f"Erreur lors de la mise à jour du fill: {e}")
            return False

    def get_active_trades(self):
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM active_trades WHERE status = 'OPEN'")
            return cursor.fetchall()

    def get_performance_summary(self, mode: str = "PAPER") -> Dict[str, Any]:
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM performance_metrics WHERE execution_mode = ?", (mode,))
            row = cursor.fetchone()
            if not row:
                return {}
            return dict(row)

    def get_safety_flags(self) -> Dict[str, Any]:
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM safety_flags WHERE id = 1")
            row = cursor.fetchone()
            if not row:
                return {}
            return dict(row)

    def set_safety_flag(self, strict_maker_only: bool, max_kelly_pct: float, reason: str) -> None:
        with self._lock:
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
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT * FROM historical_performance
                ORDER BY settled_at DESC LIMIT ?
            """, (limit,))
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def _resolve_position_table(position_id: str) -> str:
        return "paper_positions" if str(position_id).startswith("paper-") else "positions"

    def set_position_sltp(self, position_id: str, stop_loss_pct: float = 0.0, take_profit_pct: float = 0.0) -> None:
        with self._lock:
            cursor = self.conn.cursor()
            table = self._resolve_position_table(position_id)
            cursor.execute(
                f"UPDATE {table} SET stop_loss_pct = ?, take_profit_pct = ? WHERE position_id = ?",
                (stop_loss_pct, take_profit_pct, position_id),
            )
            self.conn.commit()

    def set_position_stop_loss_cents(self, position_id: str, stop_loss_cents: float = 0.0) -> None:
        with self._lock:
            cursor = self.conn.cursor()
            table = self._resolve_position_table(position_id)
            try:
                cursor.execute(
                    f"UPDATE {table} SET stop_loss_cents = ? WHERE position_id = ?",
                    (float(stop_loss_cents), position_id),
                )
                self.conn.commit()
            except sqlite3.OperationalError:
                pass

    def get_positions_due_for_exit(self, current_prices: dict[str, float]) -> list[dict]:
        positions = self.get_open_positions() + self.get_paper_positions("OPEN")
        due: list[dict] = []
        for pos in positions:
            ticker = pos.get("ticker", "")
            price = current_prices.get(ticker)
            if price is None or price <= 0:
                continue
            entry = float(pos.get("entry_price", 0.0))
            side = pos.get("side", "BUY")
            sl = float(pos.get("stop_loss_pct", 0.0) or 0.0)
            sl_cents = float(pos.get("stop_loss_cents", 0.0) or 0.0)
            tp = float(pos.get("take_profit_pct", 0.0) or 0.0)
            if entry <= 0:
                continue
            ret = (price - entry) / entry
            adverse_move = entry - price
            if side in ("SELL", "NO", "SHORT"):
                ret = -ret
                adverse_move = price - entry
            if sl_cents > 0 and adverse_move >= sl_cents:
                due.append({**pos, "exit_reason": "stop_loss_cents", "exit_price": price})
            elif sl > 0 and ret <= -sl:
                due.append({**pos, "exit_reason": "stop_loss", "exit_price": price})
            elif tp > 0 and ret >= tp:
                due.append({**pos, "exit_reason": "take_profit", "exit_price": price})
        return due

    def close_position(
        self,
        position_id: str,
        exit_price: Optional[float] = None,
        pnl: Optional[float] = None,
        exit_reason: Optional[str] = None,
    ) -> None:
        with self._lock:
            cursor = self.conn.cursor()
            table = self._resolve_position_table(position_id)
            if exit_price is not None:
                if table == "paper_positions":
                    is_win = 1 if (pnl is not None and pnl > 0) else 0
                    cursor.execute(
                        "UPDATE paper_positions SET status = 'CLOSED', exit_price = ?, pnl = ?, "
                        "is_win = ?, closed_at = CURRENT_TIMESTAMP WHERE position_id = ?",
                        (exit_price, pnl, is_win, position_id),
                    )
                else:
                    cursor.execute(
                        "UPDATE positions SET status = 'CLOSED', exit_price = ?, pnl = ?, "
                        "closed_at = CURRENT_TIMESTAMP WHERE position_id = ?",
                        (exit_price, pnl, position_id),
                    )
            else:
                cursor.execute(
                    f"UPDATE {table} SET status = 'CLOSED', closed_at = CURRENT_TIMESTAMP "
                    "WHERE position_id = ?",
                    (position_id,),
                )
            self.conn.commit()
        if exit_reason:
            logger.info("Position %s closed with reason: %s", position_id, exit_reason)

    def get_global_drawdown(self) -> float:
        """
        Calcule le Drawdown Global sur les dernières 24 heures.
        Retourne une valeur <= 0 (ex: -0.10 pour -10%).
        """
        try:
            with self._transaction() as cursor:
                cursor.execute("SELECT total_capital FROM capital_allocation ORDER BY id DESC LIMIT 1")
                row = cursor.fetchone()
                if not row:
                    return 0.0
                current_capital = float(row["total_capital"])

                cursor.execute("""
                    SELECT MAX(total_capital) as peak_capital
                    FROM capital_allocation
                    WHERE updated_at >= datetime('now', '-1 day')
                """)
                peak_row = cursor.fetchone()
                if not peak_row or not peak_row["peak_capital"]:
                    return 0.0

                peak_capital = float(peak_row["peak_capital"])

                if peak_capital <= 0:
                    return 0.0

                drawdown = (current_capital - peak_capital) / peak_capital
                return drawdown
        except Exception as e:
            logger.error(f"Erreur lors du calcul du drawdown global: {e}")
            return 0.0
