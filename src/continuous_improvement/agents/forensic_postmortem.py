import asyncio
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from dataclasses import dataclass

logger = logging.getLogger("ForensicAgent")


@dataclass
class TradeAnalysis:
    trade_id: str
    ticker: str
    side: str
    is_win: bool
    gross_pnl: float
    net_pnl: float
    friction_cost: float
    slippage_pct: float
    execution_loss_pct: float
    model_error: Optional[float]
    alpha_type: str
    conclusion: str
    timestamp: str


class ForensicPostMortemAgent:
    """
    Agent d'analyse forensique des trades clos.
    Compare le Model Alpha et l'Execution Alpha pour générer les conclusions.
    """

    def __init__(self, ledger=None):
        self.ledger = ledger
        self._analyses: List[TradeAnalysis] = []
        self._running = False
        self._check_interval = 30

    async def start(self):
        self._running = True
        asyncio.create_task(self._check_pending_trades())
        logger.info("Forensic agent started")

    async def stop(self):
        self._running = False

    async def _check_pending_trades(self):
        while self._running:
            try:
                await self._analyze_closed_trades()
            except Exception as e:
                logger.error(f"Forensic check error: {e}")
            await asyncio.sleep(self._check_interval)

    async def _analyze_closed_trades(self):
        if not self.ledger:
            return

        try:
            from database.ledger_db import Ledger
            ledger = Ledger()
            history = ledger.get_historical_performance(limit=20)

            for trade in history:
                if trade.get("model_error") is None:
                    await self._analyze_trade(trade)

        except Exception as e:
            logger.error(f"Failed to analyze trades: {e}")

    async def _analyze_trade(self, trade: Dict) -> TradeAnalysis:
        trade_id = trade.get("trade_id", "unknown")
        is_win = bool(trade.get("is_win", 0))
        gross_pnl = trade.get("gross_pnl", 0)
        net_pnl = trade.get("net_pnl", 0)
        friction_cost = trade.get("friction_cost", 0)
        slippage = trade.get("slippage", 0)
        execution_loss_pct = trade.get("execution_loss_pct", 0)

        alpha_type = "UNKNOWN"
        conclusion = ""
        model_error = None

        if not is_win:
            if execution_loss_pct >= 0.30:
                alpha_type = "EXECUTION_ALPHA"
                model_error = abs(slippage * trade.get("size", 1)) / abs(gross_pnl) if gross_pnl != 0 else 0
                conclusion = "Exécution compromise par spread toxique ou slippage. Forcer PassiveExecutor mode strict post-only. Kelly réduit."
            else:
                alpha_type = "MODEL_ALPHA"
                model_error = 1.0
                conclusion = "Erreur de modèle: signal incorrect malgré exécution parfaite. Trigger OOD detection ou retrain FreqAI anticipé."
        else:
            alpha_type = "SUCCESS"
            conclusion = "Trade gagnant - exécution et signal tous deux corrects."
            model_error = 0.0

        analysis = TradeAnalysis(
            trade_id=trade_id,
            ticker=trade.get("ticker", ""),
            side=trade.get("side", ""),
            is_win=is_win,
            gross_pnl=gross_pnl,
            net_pnl=net_pnl,
            friction_cost=friction_cost,
            slippage_pct=slippage,
            execution_loss_pct=execution_loss_pct,
            model_error=model_error,
            alpha_type=alpha_type,
            conclusion=conclusion,
            timestamp=datetime.now(timezone.utc).isoformat()
        )

        self._analyses.append(analysis)
        if len(self._analyses) > 100:
            self._analyses.pop(0)

        logger.info(f"Forensic analysis [{alpha_type}]: {trade_id} {analysis.conclusion[:50]}...")

        return analysis

    def get_performance_summary(self) -> Dict[str, Any]:
        if not self._analyses:
            return {"total": 0, "wins": 0, "losses": 0}

        total = len(self._analyses)
        wins = sum(1 for a in self._analyses if a.is_win)
        losses = total - wins

        execution_alpha = sum(1 for a in self._analyses if a.alpha_type == "EXECUTION_ALPHA")
        model_alpha = sum(1 for a in self._analyses if a.alpha_type == "MODEL_ALPHA")

        total_pnl = sum(a.net_pnl for a in self._analyses)
        avg_win_pnl = sum(a.net_pnl for a in self._analyses if a.is_win and a.net_pnl > 0) / max(wins, 1)
        avg_loss_pnl = sum(a.net_pnl for a in self._analyses if not a.is_win and a.net_pnl < 0) / max(losses, 1)

        return {
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": wins / total if total > 0 else 0,
            "execution_alpha_count": execution_alpha,
            "model_alpha_count": model_alpha,
            "total_pnl": total_pnl,
            "avg_win": avg_win_pnl,
            "avg_loss": avg_loss_pnl,
            "profit_factor": abs(avg_win_pnl / avg_loss_pnl) if avg_loss_pnl != 0 else 0
        }

    def get_recent_analyses(self, limit: int = 10) -> List[TradeAnalysis]:
        return self._analyses[-limit:]

    def format_forensic_report(self) -> str:
        summary = self.get_performance_summary()

        lines = [
            "🔍 *FORENSIC POST-MORTEM REPORT*",
            "───────────────────────────────",
            f"📊 *Total Trades:* `{summary['total_trades']}`",
            f"✅ *Wins:* `{summary['wins']}` | ❌ *Losses:* `{summary['losses']}`",
            f"📈 *Win Rate:* `{summary['win_rate']*100:.1f}%`",
            f"💰 *Total PnL:* `${summary['total_pnl']:.4f}`",
            "",
            f"⚡ *Execution Alpha:* `{summary['execution_alpha_count']}`",
            f"🧠 *Model Alpha:* `{summary['model_alpha_count']}`",
            "",
            f"📊 *Avg Win:* `${summary['avg_win']:.4f}` | 📉 *Avg Loss:* `${summary['avg_loss']:.4f}`",
            f"📐 *Profit Factor:* `{summary['profit_factor']:.2f}`",
        ]

        return "\n".join(lines)