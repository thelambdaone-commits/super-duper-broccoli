import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

from ledger.ledger_db import Ledger
from utils.output_formatter import TelegramOutputFormatter

logger = logging.getLogger("PerformanceAttribution")

from utils.config_loader import TRADING_PARAMS

FRICTION_COST_PER_CONTRACT = TRADING_PARAMS["FRICTION_PER_CONTRACT"]
EXECUTION_LOSS_THRESHOLD = TRADING_PARAMS["EXECUTION_LOSS_THRESHOLD"]
MIN_EDGE_THRESHOLD = TRADING_PARAMS["MIN_EDGE_THRESHOLD"]
MAX_RESOLUTION_WAIT_SECONDS = TRADING_PARAMS["MAX_RESOLUTION_WAIT_HOURS"] * 3600


class PerformanceAttribution:
    def __init__(self, ledger: Optional[Ledger] = None, telegram_broadcaster=None):
        self.ledger = ledger
        self.broadcaster = telegram_broadcaster
        self._running = False
        self._check_interval = TRADING_PARAMS["RESOLUTION_CHECK_INTERVAL"]

    async def start(self):
        self._running = True
        asyncio.create_task(self._verifier_resolution_marches())
        logger.info("Performance Attribution Engine started")

    async def stop(self):
        self._running = False

    async def _verifier_resolution_marches(self):
        while self._running:
            try:
                await self._check_and_resolve_pending_trades()
            except Exception as e:
                logger.error(f"Resolution checker error: {e}")
            await asyncio.sleep(self._check_interval)

    async def _check_and_resolve_pending_trades(self):
        if not self.ledger:
            return

        cursor = self.ledger.conn.cursor()
        cursor.execute("""
            SELECT trade_id, ticker, condition_id, side, entry_price, size,
                   capital_engaged, mid_price_at_signal, fill_price, friction_cost,
                   resolution_timestamp, confidence, signal_source, regime_label
            FROM active_trades
            WHERE status = 'OPEN' AND resolution_timestamp <= ?
        """, (time.time(),))

        pending_trades = cursor.fetchall()

        for trade in pending_trades:
            await self._resolve_trade(dict(trade))

    async def _resolve_trade(self, trade: Dict[str, Any]) -> None:
        trade_id = trade["trade_id"]
        ticker = trade["ticker"]
        condition_id = trade["condition_id"]
        side = trade["side"]
        entry_price = trade["entry_price"]
        size = trade["size"]
        capital_engaged = trade["capital_engaged"]
        mid_price_signal = trade["mid_price_at_signal"]
        fill_price = trade["fill_price"]
        friction_cost = trade["friction_cost"]

        outcome = await self._fetch_polymarket_resolution(condition_id)

        if outcome is None:
            resolution_timestamp = trade.get("resolution_timestamp")
            try:
                resolution_epoch = float(resolution_timestamp)
            except (TypeError, ValueError):
                resolution_epoch = 0.0
            age_seconds = time.time() - resolution_epoch if resolution_epoch > 0 else MAX_RESOLUTION_WAIT_SECONDS + 1
            if age_seconds < MAX_RESOLUTION_WAIT_SECONDS:
                logger.warning(f"Could not resolve trade {trade_id}, retrying later")
                return

            logger.warning(
                "Resolution unavailable for trade %s after %.1f hours; applying conservative fallback close.",
                trade_id,
                age_seconds / 3600.0,
            )
            outcome = 0.0 if side == "YES" else 1.0
            exit_price = fill_price
            gross_pnl = -abs(friction_cost)
            net_pnl = gross_pnl
            slippage = abs(fill_price - mid_price_signal)
            execution_loss_pct = 1.0 if abs(gross_pnl) > 0 else 0.0
            await self._cloturer_et_sceller_position(
                trade,
                outcome,
                exit_price,
                gross_pnl,
                net_pnl,
                slippage,
                execution_loss_pct,
                False,
            )
            await self._trigger_safety_flag(trade_id, execution_loss_pct)
            await self._analyser_execution_alpha(trade, False, gross_pnl, net_pnl, slippage, execution_loss_pct)
            return

        is_win = (outcome == 1.0 and side == "YES") or (outcome == 0.0 and side == "NO")

        if side == "YES":
            exit_price = outcome
            gross_pnl = (exit_price - entry_price) * size if is_win else -(entry_price * size)
        else:
            exit_price = 1.0 - outcome
            gross_pnl = (entry_price - exit_price) * size if is_win else -(entry_price * size)

        net_pnl = gross_pnl - friction_cost
        slippage = abs(fill_price - mid_price_signal)

        execution_loss_pct = 0.0
        if abs(gross_pnl) > 0:
            execution_loss_pct = abs(slippage * size) / abs(gross_pnl)

        await self._cloturer_et_sceller_position(trade, outcome, exit_price, gross_pnl, net_pnl, slippage, execution_loss_pct, is_win)

        if execution_loss_pct >= EXECUTION_LOSS_THRESHOLD:
            await self._trigger_safety_flag(trade_id, execution_loss_pct)

        await self._analyser_execution_alpha(trade, is_win, gross_pnl, net_pnl, slippage, execution_loss_pct)

    async def _fetch_polymarket_resolution(self, condition_id: str) -> Optional[float]:
        url = f"https://clob.polymarket.com/markets/{condition_id}/resolution"

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    return float(data.get("outcome", 0))
        except Exception as e:
            logger.error(f"Failed to fetch resolution for {condition_id}: {e}")

        alt_url = f"https://clob.polymarket.com/conditions/{condition_id}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(alt_url)
                if resp.status_code == 200:
                    data = resp.json()
                    return float(data.get("result", {}).get("outcome", 0))
        except Exception as e:
            logger.error(f"Alt resolution fetch failed for {condition_id}: {e}")

        return None

    async def _cloturer_et_sceller_position(
        self,
        trade: Dict[str, Any],
        outcome: float,
        exit_price: float,
        gross_pnl: float,
        net_pnl: float,
        slippage: float,
        execution_loss_pct: float,
        is_win: bool
    ) -> None:
        if not self.ledger:
            return

        trade_id = trade["trade_id"]

        cursor = self.ledger.conn.cursor()

        cursor.execute("""
            INSERT INTO historical_performance (
                trade_id, ticker, side, entry_price, exit_price, size,
                capital_engaged, gross_pnl, friction_cost, net_pnl, is_win,
                mid_price_at_signal, fill_price, slippage, execution_loss_pct,
                alpha_source, confidence, regime_label, resolution_time
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            trade_id, trade["ticker"], trade["side"], trade["entry_price"],
            exit_price, trade["size"], trade["capital_engaged"],
            gross_pnl, trade["friction_cost"], net_pnl, 1 if is_win else 0,
            trade["mid_price_at_signal"], trade["fill_price"], slippage,
            execution_loss_pct, trade["signal_source"], trade["confidence"],
            trade["regime_label"], datetime.now(timezone.utc).isoformat()
        ))

        cursor.execute("DELETE FROM active_trades WHERE trade_id = ?", (trade_id,))

        self._update_performance_metrics("PAPER", net_pnl, is_win, trade["friction_cost"])

        self.ledger.conn.commit()

        await self._broadcast_trade_outcome(trade, exit_price, net_pnl, is_win, execution_loss_pct)

        logger.info(f"Trade {trade_id} settled: {'WIN' if is_win else 'LOSS'}, PnL: {net_pnl:.4f}")

    def _update_performance_metrics(
        self, execution_mode: str, net_pnl: float, is_win: bool, friction: float
    ) -> None:
        cursor = self.ledger.conn.cursor()

        cursor.execute(
            "INSERT OR IGNORE INTO performance_metrics (execution_mode) VALUES (?)",
            (execution_mode,),
        )

        cursor.execute("""
            SELECT total_trades, winning_trades, losing_trades, total_gross_pnl,
                   total_net_pnl, total_friction, avg_win, avg_loss
            FROM performance_metrics WHERE execution_mode = ?
        """, (execution_mode,))

        metrics = cursor.fetchone()

        if not metrics:
            logger.warning(f"No performance_metrics row for mode {execution_mode}, skipping")
            return

        total_trades = metrics["total_trades"] + 1
        winning_trades = metrics["winning_trades"] + (1 if is_win else 0)
        losing_trades = metrics["losing_trades"] + (0 if is_win else 1)

        total_gross_pnl = metrics["total_gross_pnl"] + net_pnl + friction
        total_net_pnl = metrics["total_net_pnl"] + net_pnl
        total_friction = metrics["total_friction"] + friction

        win_rate = winning_trades / total_trades if total_trades > 0 else 0.0

        avg_win = (metrics["avg_win"] * winning_trades + (net_pnl if is_win else 0)) / winning_trades if winning_trades > 0 else 0.0

        avg_loss = (metrics["avg_loss"] * losing_trades + (net_pnl if not is_win else 0)) / losing_trades if losing_trades > 0 else 0.0

        profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else 0.0

        cursor.execute("""
            UPDATE performance_metrics SET
                total_trades = ?, winning_trades = ?, losing_trades = ?,
                total_gross_pnl = ?, total_net_pnl = ?, total_friction = ?,
                win_rate = ?, profit_factor = ?, avg_win = ?, avg_loss = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE execution_mode = ?
        """, (total_trades, winning_trades, losing_trades, total_gross_pnl,
              total_net_pnl, total_friction, win_rate, profit_factor, avg_win,
              avg_loss, execution_mode))

    async def _trigger_safety_flag(self, trade_id: str, execution_loss_pct: float) -> None:
        cursor = self.ledger.conn.cursor()

        cursor.execute("""
            UPDATE safety_flags SET
                strict_maker_only = 1,
                triggered_at = CURRENT_TIMESTAMP,
                reason = ?
            WHERE id = 1
        """, (f"Execution loss {execution_loss_pct*100:.1f}% exceeds {EXECUTION_LOSS_THRESHOLD*100}% threshold on trade {trade_id}",))

        self.ledger.conn.commit()

        logger.warning(f"SAFETY FLAG TRIGGERED: Strict Maker-Only mode enabled due to {execution_loss_pct*100:.1f}% execution loss")

        if self.broadcaster:
            await self.broadcaster.send(f"🚨 *SAFETY FLAG TRIGGERED*\n\nExecution loss: {execution_loss_pct*100:.1f}%\nMode: *STRICT MAKER-ONLY* enabled\n\nKelly sizing reduced to 25%")

    async def _analyser_execution_alpha(
        self,
        trade: Dict[str, Any],
        is_win: bool,
        gross_pnl: float,
        net_pnl: float,
        slippage: float,
        execution_loss_pct: float
    ) -> None:
        model_error = None
        alpha_type = "UNKNOWN"

        if not is_win:
            if execution_loss_pct >= EXECUTION_LOSS_THRESHOLD:
                model_error = abs(slippage * trade["size"]) / abs(gross_pnl) if gross_pnl != 0 else 0
                alpha_type = "EXECUTION_ALPHA"
                conclusion = "Exécution compromis par spread toxique ou slippage.Forcer PassiveExecutor en mode strict post-only.Kelly réduit."
            else:
                alpha_type = "MODEL_ALPHA"
                model_error = 1.0
                conclusion = "Erreur de modèle: signal incorrect malgré exécution parfaite.Trigger OOD detection ou retrain FreqAI anticipé."

            cursor = self.ledger.conn.cursor()
            cursor.execute("""
                UPDATE historical_performance SET
                    model_error = ? WHERE trade_id = ?
            """, (model_error, trade["trade_id"]))
            self.ledger.conn.commit()

            logger.info(f"Post-Mortem [{alpha_type}]: {conclusion}")

            if self.broadcaster:
                await self.broadcaster.send(
                    f"📊 *POST-MORTEM — {trade['trade_id'][:8]}*\n\n"
                    f"Type: *{alpha_type}*\n"
                    f"Conclusion: {conclusion}"
                )

    async def _broadcast_trade_outcome(
        self,
        trade: Dict[str, Any],
        exit_price: float,
        net_pnl: float,
        is_win: bool,
        execution_loss_pct: float
    ) -> None:
        if not self.broadcaster:
            return

        formatter = TelegramOutputFormatter()
        outcome_msg = formatter.signal_alert(
            ticker=trade["ticker"],
            side=trade["side"],
            entry=trade["entry_price"],
            exit=exit_price,
            size=trade["size"],
            pnl=net_pnl,
            is_win=is_win,
            confidence=trade["confidence"],
            regime=trade.get("regime_label", "UNKNOWN"),
            slippage=execution_loss_pct
        )

        await self.broadcaster.send(outcome_msg)

    def enregistrer_trade(
        self,
        ticker: str,
        condition_id: str,
        side: str,
        entry_price: float,
        size: float,
        mid_price_at_signal: float,
        fill_price: float,
        confidence: float,
        signal_source: str,
        regime_label: str,
        resolution_timestamp: float
    ) -> str:
        if not self.ledger:
            return ""

        trade_id = f"trade_{uuid.uuid4().hex[:12]}"

        capital_engaged = entry_price * size
        friction_cost = FRICTION_COST_PER_CONTRACT * size

        cursor = self.ledger.conn.cursor()
        cursor.execute("""
            INSERT INTO active_trades (
                trade_id, ticker, condition_id, side, entry_price, size,
                capital_engaged, mid_price_at_signal, fill_price, friction_cost,
                confidence, signal_source, regime_label, resolution_timestamp, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')
        """, (
            trade_id, ticker, condition_id, side, entry_price, size,
            capital_engaged, mid_price_at_signal, fill_price, friction_cost,
            confidence, signal_source, regime_label, resolution_timestamp
        ))

        self.ledger.conn.commit()

        logger.info(f"Trade recorded: {trade_id} {ticker} {side} @ {entry_price}")
        return trade_id

    def get_performance_summary(self, execution_mode: str = "PAPER") -> Dict[str, Any]:
        if not self.ledger:
            return {}

        cursor = self.ledger.conn.cursor()
        cursor.execute("""
            SELECT * FROM performance_metrics WHERE execution_mode = ?
        """, (execution_mode,))

        metrics = cursor.fetchone()

        if not metrics:
            return {}

        cursor.execute("""
            SELECT COUNT(*) as cnt, AVG(execution_loss_pct) as avg_exec_loss
            FROM historical_performance WHERE is_win = 0
        """)

        losing_stats = cursor.fetchone()

        return {
            "execution_mode": metrics["execution_mode"],
            "total_trades": metrics["total_trades"],
            "win_rate": metrics["win_rate"] * 100,
            "profit_factor": metrics["profit_factor"],
            "total_net_pnl": metrics["total_net_pnl"],
            "total_friction": metrics["total_friction"],
            "max_drawdown": metrics["max_drawdown"],
            "avg_win": metrics["avg_win"],
            "avg_loss": metrics["avg_loss"],
            "losing_trades": metrics["losing_trades"],
            "avg_execution_loss_on_loss": losing_stats["avg_exec_loss"] * 100 if losing_stats else 0
        }

    def filtrer_signal_emission(self, model_prob: float, market_price: float) -> bool:
        edge = abs(model_prob - market_price)
        return edge >= MIN_EDGE_THRESHOLD

    def get_safety_flags(self) -> Dict[str, Any]:
        if not self.ledger:
            return {}

        cursor = self.ledger.conn.cursor()
        cursor.execute("SELECT * FROM safety_flags WHERE id = 1")
        flags = cursor.fetchone()

        if not flags:
            return {}

        return {
            "strict_maker_only": bool(flags["strict_maker_only"]),
            "max_kelly_pct": flags["max_kelly_pct"],
            "triggered_at": flags["triggered_at"],
            "reason": flags["reason"]
        }

    def reset_safety_flags(self) -> None:
        if not self.ledger:
            return

        cursor = self.ledger.conn.cursor()
        cursor.execute("""
            UPDATE safety_flags SET
                strict_maker_only = 0,
                max_kelly_pct = 0.25,
                triggered_at = NULL,
                reason = NULL
            WHERE id = 1
        """)
        self.ledger.conn.commit()
        logger.info("Safety flags reset")
