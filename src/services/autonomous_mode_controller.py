from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from core.strategy_lifecycle_manager import StrategyLifecycleManager, StrategyPhase
from database.ledger_db import Ledger

logger = logging.getLogger("AutonomousModeController")


@dataclass(frozen=True)
class ModeDecision:
    mode: str
    reason: str
    profit_directive: str
    real_ready: bool = False
    shadow_ready: bool = False


@dataclass
class AutonomousModeConfig:
    min_paper_trades_for_shadow: int = 3
    min_paper_trades_for_real: int = 8
    min_win_rate_for_shadow: float = 0.50
    min_win_rate_for_real: float = 0.55
    min_net_pnl_for_shadow: float = 0.0
    min_net_pnl_for_real: float = 0.10
    max_global_drawdown: float = 0.15
    min_real_capital: float = 1.0


class AutonomousModeController:
    """
    Chooses PAPER/SHADOW/PROD from measured edge and safety state.

    It is profit-seeking, but not reckless: PROD is only selected when strategies
    have reached REAL lifecycle state, paper metrics are profitable, capital is
    available, and production prerequisites are present.
    """

    def __init__(
        self,
        ledger: Ledger,
        lifecycle: StrategyLifecycleManager,
        config: AutonomousModeConfig | None = None,
    ) -> None:
        self.ledger = ledger
        self.lifecycle = lifecycle
        self.config = config or AutonomousModeConfig()

    def decide(self) -> ModeDecision:
        if _env_true("AUTONOMOUS_DISABLE_TRADING"):
            return ModeDecision("REPLAY", "AUTONOMOUS_DISABLE_TRADING is enabled", "Preserve capital")

        drawdown = self._global_drawdown()
        if drawdown <= -abs(self.config.max_global_drawdown):
            return ModeDecision("PAPER", f"Global drawdown guard active ({drawdown:.2%})", "Recover edge in simulation")

        force_prod = self._force_prod_enabled()

        paper_perf = self.ledger.get_performance_summary("PAPER") or {}
        trades = int(paper_perf.get("total_trades", 0) or 0)
        win_rate = float(paper_perf.get("win_rate", 0.0) or 0.0)
        net_pnl = float(paper_perf.get("total_net_pnl", 0.0) or 0.0)

        has_sanity_or_real = any(
            state.phase in {StrategyPhase.SANITY, StrategyPhase.REAL}
            for state in self.lifecycle.states.values()
        )
        has_real_strategy = any(
            state.phase == StrategyPhase.REAL and state.allocation_usdc > 0
            for state in self.lifecycle.states.values()
        )

        shadow_ready = (
            has_sanity_or_real
            and trades >= self.config.min_paper_trades_for_shadow
            and win_rate >= self.config.min_win_rate_for_shadow
            and net_pnl > self.config.min_net_pnl_for_shadow
        )
        real_ready = (
            has_real_strategy
            and trades >= self.config.min_paper_trades_for_real
            and win_rate >= self.config.min_win_rate_for_real
            and net_pnl > self.config.min_net_pnl_for_real
            and self._capital_available() >= self.config.min_real_capital
            and self._prod_prerequisites_present()
        )

        directive = (
            "Maximize expected value with bounded downside: prefer maker/mean-reversion edges, "
            "cut losers via SL, let winners hit TP/trailing exits."
        )
        if force_prod and self._capital_available() >= self.config.min_real_capital and self._prod_prerequisites_present():
            return ModeDecision(
                "PROD",
                "Forced PROD override enabled for non-interactive runtime",
                directive,
                True,
                True,
            )
        if real_ready:
            return ModeDecision("PROD", "REAL strategies and profitability gates passed", directive, True, True)
        if shadow_ready:
            return ModeDecision("SHADOW", "Paper profitability gates passed; validating live execution path", directive, False, True)
        return ModeDecision("PAPER", "Insufficient proven edge for live capital", directive, False, False)

    def apply(self) -> ModeDecision:
        current = self.ledger.get_execution_mode()
        if self.ledger.is_manual_mode():
            return ModeDecision(current, "Manual override active", "Honor user command")

        decision = self.decide()
        if current != decision.mode:
            self.ledger.set_execution_mode(decision.mode)
            logger.warning("Autonomous execution mode changed: %s -> %s (%s)", current, decision.mode, decision.reason)
        return decision

    def _global_drawdown(self) -> float:
        try:
            return float(self.ledger.get_global_drawdown())
        except Exception:
            return 0.0

    def _capital_available(self) -> float:
        summary = self.ledger.get_capital_summary() or {}
        try:
            return float(summary.get("available_capital", 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _force_prod_enabled() -> bool:
        return _env_true("AUTONOMOUS_FORCE_PROD") or _env_true("FORCE_PROD")

    def _prod_prerequisites_present(self) -> bool:
        if not _env_true("AUTONOMOUS_REAL_EXECUTION_ENABLED"):
            logger.warning("PROD prerequisites missing: AUTONOMOUS_REAL_EXECUTION_ENABLED is not 'true'")
            return False
        
        mode = os.getenv("MODE", "").upper()
        real_env = _env_true("REAL")
        if not (mode == "PRD" or real_env):
            logger.warning(f"PROD prerequisites missing: MODE={mode} and REAL={real_env} (one must be PRD/true)")
            return False

        return True


def select_autonomous_execution_mode(ledger: Ledger, lifecycle: StrategyLifecycleManager | None = None) -> ModeDecision:
    manager = lifecycle or StrategyLifecycleManager()
    return AutonomousModeController(ledger, manager).decide()


def _env_true(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}
