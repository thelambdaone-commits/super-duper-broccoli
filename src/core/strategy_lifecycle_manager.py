from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping

from strategies.base_strategy import MarketFeatures, StrategySignal
from strategies.polymarket_strategy_factory import (
    PolymarketStrategy,
    build_default_polymarket_strategies,
)

logger = logging.getLogger("StrategyLifecycleManager")


class StrategyPhase(str, Enum):
    BACKTEST = "BACKTEST"
    PAPER = "PAPER"
    SANITY = "SANITY"
    REAL = "REAL"
    DISABLED = "DISABLED"


@dataclass
class BacktestMetrics:
    total_profit: float = 0.0
    sharpe: float = 0.0
    max_drawdown: float = 0.0
    trade_count: int = 0
    win_rate: float = 0.0

    @property
    def passed(self) -> bool:
        return self.trade_count > 0


@dataclass
class PaperMetrics:
    total_profit: float = 0.0
    trade_count: int = 0
    consecutive_losses: int = 0
    max_slippage: float = 0.0
    rejected_orders: int = 0
    started_at: float = field(default_factory=time.time)
    last_update: float = field(default_factory=time.time)

    @property
    def runtime_seconds(self) -> float:
        return max(0.0, self.last_update - self.started_at)


@dataclass
class SanityReport:
    heartbeat_ok: bool = False
    tensor_fallback_ok: bool = False
    strict_json_ok: bool = False
    risk_veto_ok: bool = True
    checked_at: float = field(default_factory=time.time)

    @property
    def passed(self) -> bool:
        return self.heartbeat_ok and self.tensor_fallback_ok and self.strict_json_ok and self.risk_veto_ok


from utils.config_loader import TRADING_PARAMS

@dataclass
class StrategyLifecycleConfig:
    min_sharpe: float = TRADING_PARAMS["MIN_SHARPE_BACKTEST"]
    min_profit: float = 0.0
    max_drawdown: float = 0.20
    min_backtest_trades: int = 3
    min_paper_trades: int = TRADING_PARAMS["MIN_PAPER_TRADES"]
    min_paper_profit: float = 0.0

    max_paper_slippage: float = 0.04
    max_rejected_orders: int = 0
    max_consecutive_losses: int = 3
    initial_real_allocation: float = 10.0
    dashboard_path: str = "STRATEGY_AUTONOMOUS_DASHBOARD.md"
    state_path: str = "user_data/data/strategy_lifecycle_state.json"


@dataclass
class StrategyLifecycleState:
    strategy_id: str
    name: str
    phase: StrategyPhase = StrategyPhase.BACKTEST
    backtest: BacktestMetrics = field(default_factory=BacktestMetrics)
    paper: PaperMetrics = field(default_factory=PaperMetrics)
    sanity: SanityReport = field(default_factory=SanityReport)
    allocation_usdc: float = 0.0
    disabled_reason: str = ""
    force_real: bool = False
    mutations: list[dict[str, Any]] = field(default_factory=list)
    pnl_history: list[dict[str, Any]] = field(default_factory=list)
    updated_at: float = field(default_factory=time.time)


class StrategyLifecycleManager:
    """
    Gated strategy promotion manager.

    This manager never bypasses PortfolioRiskEngine. A REAL promotion only marks a
    strategy as eligible with a small allocation; execution code must still route
    every signal through the existing deterministic risk gate.
    """

    def __init__(
        self,
        strategies: Iterable[PolymarketStrategy] | None = None,
        config: StrategyLifecycleConfig | None = None,
        risk_engine: Any | None = None,
        notifier: Any | None = None,
    ) -> None:
        self.config = config or StrategyLifecycleConfig()
        self.strategies = {s.strategy_id: s for s in (strategies or build_default_polymarket_strategies())}
        self.risk_engine = risk_engine
        self.notifier = notifier
        self.states: dict[str, StrategyLifecycleState] = {
            sid: StrategyLifecycleState(strategy_id=sid, name=strategy.name)
            for sid, strategy in self.strategies.items()
        }
        self._load_state()

    def register_strategy(self, strategy: PolymarketStrategy) -> None:
        sid = strategy.strategy_id
        if sid not in self.strategies:
            self.strategies[sid] = strategy
            self.states[sid] = StrategyLifecycleState(strategy_id=sid, name=strategy.name)
            logger.info(f"New strategy registered in lifecycle: {sid} ({strategy.name})")
            # Try to reload if state already existed in file
            self._load_state()

    def run_backtests(self, rows_by_strategy: Mapping[str, list[Mapping[str, Any]]] | list[Mapping[str, Any]]) -> dict[str, BacktestMetrics]:
        results: dict[str, BacktestMetrics] = {}
        for strategy_id, strategy in self.strategies.items():
            rows = rows_by_strategy.get(strategy_id, []) if isinstance(rows_by_strategy, Mapping) else rows_by_strategy
            metrics = self.backtest_strategy(strategy, rows)
            state = self.states[strategy_id]
            state.backtest = metrics
            state.updated_at = time.time()
            if self._backtest_gate(metrics):
                state.phase = StrategyPhase.PAPER
            elif state.phase == StrategyPhase.BACKTEST:
                state.disabled_reason = "Backtest gate not yet passed"
            results[strategy_id] = metrics
        self.persist_state()
        self.write_dashboard()
        return results

    def backtest_strategy(self, strategy: PolymarketStrategy, rows: list[Mapping[str, Any]]) -> BacktestMetrics:
        if len(rows) < 2:
            return BacktestMetrics()

        pnls: list[float] = []
        wins = 0
        for current, nxt in zip(rows, rows[1:]):
            features = MarketFeatures.from_mapping(current)
            signal = strategy.generate_signal(features)
            if signal is None:
                continue
            next_price = _safe_float(nxt.get("price") or nxt.get("mid_price"), features.price)
            direction = 1.0 if signal.side.upper() in {"BUY", "YES", "LONG"} else -1.0
            friction = max(features.spread, 0.002)
            pnl = direction * (next_price - features.price) - friction
            pnls.append(float(pnl))
            if pnl > 0:
                wins += 1

        if not pnls:
            return BacktestMetrics()
        total_profit = float(sum(pnls))
        sharpe = _sharpe(pnls)
        max_drawdown = _max_drawdown(pnls)
        return BacktestMetrics(
            total_profit=total_profit,
            sharpe=sharpe,
            max_drawdown=max_drawdown,
            trade_count=len(pnls),
            win_rate=wins / len(pnls),
        )

    def record_paper_result(
        self,
        strategy_id: str,
        pnl: float,
        slippage: float = 0.0,
        rejected: bool = False,
    ) -> StrategyLifecycleState:
        state = self.states[strategy_id]
        if state.phase not in {StrategyPhase.PAPER, StrategyPhase.SANITY, StrategyPhase.REAL}:
            return state
        state.paper.trade_count += 1
        state.paper.total_profit += float(pnl)
        state.paper.max_slippage = max(state.paper.max_slippage, abs(float(slippage)))
        state.paper.rejected_orders += 1 if rejected else 0
        state.paper.consecutive_losses = state.paper.consecutive_losses + 1 if pnl < 0 else 0
        state.paper.last_update = time.time()
        state.pnl_history.append({"timestamp": state.paper.last_update, "phase": state.phase.value, "pnl": float(pnl)})
        state.updated_at = time.time()

        if state.paper.consecutive_losses >= self.config.max_consecutive_losses:
            self.demote(strategy_id, "Circuit breaker: consecutive paper/real losses")
        elif state.phase == StrategyPhase.PAPER and self._paper_gate(state.paper):
            state.phase = StrategyPhase.SANITY
        self.persist_state()
        self.write_dashboard()
        return state

    def run_sanity_checks(self, strategy_id: str, checks: Mapping[str, bool] | None = None) -> SanityReport:
        state = self.states[strategy_id]
        checks = checks or {}
        report = SanityReport(
            heartbeat_ok=bool(checks.get("heartbeat_ok", True)),
            tensor_fallback_ok=bool(checks.get("tensor_fallback_ok", True)),
            strict_json_ok=bool(checks.get("strict_json_ok", True)),
            risk_veto_ok=bool(checks.get("risk_veto_ok", True)),
        )
        state.sanity = report
        state.updated_at = time.time()
        if state.phase == StrategyPhase.SANITY and report.passed:
            state.phase = StrategyPhase.REAL
            state.allocation_usdc = self.config.initial_real_allocation
        self.persist_state()
        self.write_dashboard()
        return report

    def apply_mutation(self, strategy_id: str, updates: Mapping[str, float | int], reason: str) -> dict[str, Any]:
        strategy = self.strategies[strategy_id]
        before = asdict(strategy.parameters)
        strategy.update_parameters(updates)
        after = asdict(strategy.parameters)
        mutation = {
            "timestamp": time.time(),
            "strategy_id": strategy_id,
            "reason": reason,
            "before": before,
            "updates": dict(updates),
            "after": after,
        }
        self.states[strategy_id].mutations.append(mutation)
        self.states[strategy_id].updated_at = time.time()
        self.persist_state()
        self.write_dashboard()
        return mutation

    def demote(self, strategy_id: str, reason: str, target: StrategyPhase = StrategyPhase.PAPER) -> None:
        state = self.states[strategy_id]
        state.phase = target
        state.allocation_usdc = 0.0
        state.disabled_reason = reason
        state.updated_at = time.time()
        self._notify_critical(f"Strategy {strategy_id} demoted to {target.value}: {reason}")

    def disable(self, strategy_id: str, reason: str) -> None:
        state = self.states[strategy_id]
        state.phase = StrategyPhase.DISABLED
        state.allocation_usdc = 0.0
        state.disabled_reason = reason
        state.updated_at = time.time()
        self._notify_critical(f"Strategy {strategy_id} disabled: {reason}")
        self.persist_state()
        self.write_dashboard()

    def eligible_real_signals(self, features: Mapping[str, Any] | MarketFeatures) -> list[StrategySignal]:
        signals: list[StrategySignal] = []
        for strategy_id, strategy in self.strategies.items():
            state = self.states[strategy_id]
            if state.phase != StrategyPhase.REAL:
                continue
            signal = strategy.generate_signal(features)
            if signal is None:
                continue
            signals.append(signal)
        return signals

    def write_dashboard(self) -> None:
        path = Path(self.config.dashboard_path)
        path.parent.mkdir(parents=True, exist_ok=True) if path.parent != Path(".") else None
        lines = [
            "# Strategy Autonomous Dashboard",
            "",
            f"Updated: `{time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}`",
            "",
            "## Catalogue des Strategies",
            "",
            "| Strategy | State | Backtest Sharpe | Backtest PnL | Paper PnL | Trades | Allocation USDC | Reason |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
        for state in self.states.values():
            lines.append(
                f"| {state.name} (`{state.strategy_id}`) | {state.phase.value} | "
                f"{state.backtest.sharpe:.2f} | {state.backtest.total_profit:.4f} | "
                f"{state.paper.total_profit:.4f} | {state.paper.trade_count} | "
                f"{state.allocation_usdc:.2f} | {state.disabled_reason or '-'} |"
            )
        lines.extend(["", "## Registre des Mutations", ""])
        mutations = [m for state in self.states.values() for m in state.mutations]
        if not mutations:
            lines.append("- Aucune mutation automatique enregistree.")
        else:
            for mutation in sorted(mutations, key=lambda m: m["timestamp"], reverse=True)[-25:]:
                lines.append(
                    f"- `{_fmt_ts(mutation['timestamp'])}` `{mutation['strategy_id']}` "
                    f"{mutation['reason']} -> `{json.dumps(mutation['updates'], sort_keys=True)}`"
                )
        lines.extend(["", "## Rapport PnL", ""])
        for state in self.states.values():
            lines.append(
                f"- `{state.strategy_id}`: total paper/real tracked PnL `{state.paper.total_profit:.4f}`, "
                f"consecutive losses `{state.paper.consecutive_losses}`, max slippage `{state.paper.max_slippage:.4f}`."
            )
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def persist_state(self) -> None:
        path = Path(self.config.state_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            sid: _state_to_json(state)
            for sid, state in self.states.items()
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def _load_state(self) -> None:
        path = Path(self.config.state_path)
        if not path.exists():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to load strategy lifecycle state: %s", exc)
            return
        for sid, raw in payload.items():
            if sid not in self.states:
                continue
            try:
                self.states[sid] = _state_from_json(raw)
            except Exception as exc:
                logger.warning("Ignoring corrupt lifecycle state for %s: %s", sid, exc)

    def _backtest_gate(self, metrics: BacktestMetrics) -> bool:
        return (
            metrics.trade_count >= self.config.min_backtest_trades
            and metrics.sharpe >= self.config.min_sharpe
            and metrics.total_profit > self.config.min_profit
            and metrics.max_drawdown <= self.config.max_drawdown
        )

    def _paper_gate(self, metrics: PaperMetrics) -> bool:
        return (
            metrics.trade_count >= self.config.min_paper_trades
            and metrics.total_profit > self.config.min_paper_profit
            and metrics.max_slippage <= self.config.max_paper_slippage
            and metrics.rejected_orders <= self.config.max_rejected_orders
        )

    def _notify_critical(self, message: str) -> None:
        logger.critical(message)
        if not self.notifier:
            return
        try:
            send = getattr(self.notifier, "send", None)
            if callable(send):
                send(f"CRITICAL STRATEGY LIFECYCLE: {message}")
        except Exception as exc:
            logger.warning("Failed to notify lifecycle alert: %s", exc)


def _sharpe(pnls: list[float]) -> float:
    if len(pnls) < 2:
        return 0.0
    mean = sum(pnls) / len(pnls)
    variance = sum((p - mean) ** 2 for p in pnls) / (len(pnls) - 1)
    std = math.sqrt(variance)
    if std <= 1e-12:
        return 10.0 if mean > 0 else 0.0
    return float((mean / std) * math.sqrt(len(pnls)))


def _max_drawdown(pnls: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    gross = max(1.0, sum(abs(p) for p in pnls))
    return float(max_dd / gross)


def _safe_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _fmt_ts(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(float(ts)))


def _state_to_json(state: StrategyLifecycleState) -> dict[str, Any]:
    payload = asdict(state)
    payload["phase"] = state.phase.value
    return payload


def _state_from_json(raw: Mapping[str, Any]) -> StrategyLifecycleState:
    return StrategyLifecycleState(
        strategy_id=str(raw["strategy_id"]),
        name=str(raw["name"]),
        phase=StrategyPhase(str(raw.get("phase", StrategyPhase.BACKTEST.value))),
        backtest=BacktestMetrics(**dict(raw.get("backtest") or {})),
        paper=PaperMetrics(**dict(raw.get("paper") or {})),
        sanity=SanityReport(**dict(raw.get("sanity") or {})),
        allocation_usdc=float(raw.get("allocation_usdc", 0.0) or 0.0),
        disabled_reason=str(raw.get("disabled_reason", "")),
        force_real=bool(raw.get("force_real", False)),
        mutations=list(raw.get("mutations") or []),
        pnl_history=list(raw.get("pnl_history") or []),
        updated_at=float(raw.get("updated_at", time.time())),
    )
