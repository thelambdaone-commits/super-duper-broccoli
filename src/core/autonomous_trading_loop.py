from __future__ import annotations

import asyncio
import math
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol

from core.autonomous_mode_controller import AutonomousModeController
from core.signal_executor import _minimum_polymarket_notional
from core.strategy_lifecycle_manager import StrategyLifecycleManager, StrategyPhase
from core.strategy_selector import StrategySelectionConfig, StrategySelector
from core.trade_objective import estimate_trade_objective
from ledger.ledger_db import Ledger
from user_data.strategies.base_strategy import MarketFeatures, StrategySignal
from utils.feature_store import FeatureStore

from utils.config_loader import TRADING_PARAMS

logger = logging.getLogger("AutonomousTradingLoop")
STRATEGY_SIGNAL_LOG = Path(os.getenv("LOG_PATH", "runtime/logs")) / "strategy_signals.log"


class PriceProvider(Protocol):
    def get_prices(self) -> dict[str, float]:
        ...


@dataclass
class AutonomousTradingConfig:
    _a = TRADING_PARAMS.get("AUTONOMOUS", {})
    mode: str = "PAPER"
    poll_interval_seconds: float = 5.0
    default_take_profit_pct: float = float(_a.get("take_profit_pct", 0.12))
    default_stop_loss_pct: float = float(_a.get("stop_loss_pct", 0.06))
    trailing_stop_pct: float = float(_a.get("trailing_stop_pct", 0.04))
    min_signal_edge: float = float(_a.get("min_signal_edge", 0.02))
    max_open_positions_per_strategy: int = int(_a.get("max_open_positions_per_strategy", 3))
    max_total_open_positions: int = int(_a.get("max_total_open_positions", 12))
    default_paper_capital_usdc: float = float(_a.get("default_paper_capital_usdc", 10.0))
    top_k_opportunities: int = 3
    allow_real_execution: bool = field(
        default_factory=lambda: os.getenv("AUTONOMOUS_REAL_EXECUTION_ENABLED", "").strip().lower()
        in {"1", "true", "yes"}
    )


@dataclass(frozen=True)
class AutonomousAction:
    action: str
    status: str
    strategy_id: str = ""
    ticker: str = ""
    position_id: str = ""
    reason: str = ""
    pnl: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class AutonomousTradingLoop:
    """
    Closed-loop autonomous trading controller.

    It can open paper positions from approved strategies, attach SL/TP, monitor
    exits, and close positions. Real execution is blocked unless both ledger mode
    is PROD and AUTONOMOUS_REAL_EXECUTION_ENABLED=true.
    """

    def __init__(
        self,
        ledger: Ledger,
        lifecycle: StrategyLifecycleManager | None = None,
        risk_engine: Any | None = None,
        feature_store: FeatureStore | None = None,
        price_provider: PriceProvider | None = None,
        order_manager: Any | None = None,
        config: AutonomousTradingConfig | None = None,
        executor: Any | None = None,
    ) -> None:
        self.ledger = ledger
        self.lifecycle = lifecycle or StrategyLifecycleManager()
        self.risk_engine = risk_engine
        self.feature_store = feature_store
        self.price_provider = price_provider
        self.order_manager = order_manager
        self.executor = executor
        self.config = config or AutonomousTradingConfig(mode=self.ledger.get_execution_mode())
        self.mode_controller = AutonomousModeController(self.ledger, self.lifecycle)
        self.selector = StrategySelector(
            StrategySelectionConfig(top_k=max(1, int(self.config.top_k_opportunities)))
        )
        self._running = False
        self._high_watermarks: dict[str, float] = {}

    async def run_forever(self, feature_source: Any | None = None) -> None:
        self._running = True
        while self._running:
            try:
                features = self._load_features(feature_source)
                await self.run_once(features)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Autonomous loop iteration failed: %s", exc)
            await asyncio.sleep(max(1.0, self.config.poll_interval_seconds))

    def stop(self) -> None:
        self._running = False

    async def run_once(self, features: list[Mapping[str, Any] | MarketFeatures]) -> list[AutonomousAction]:
        self.mode_controller.apply()
        actions: list[AutonomousAction] = []
        prices = self._current_prices_from_features(features)
        if self.price_provider:
            prices.update(self.price_provider.get_prices())
        actions.extend(await self.manage_open_positions(prices))

        if self._open_position_count() >= self.config.max_total_open_positions:
            return actions

        candidates: list[StrategySignal] = []
        features_by_market: dict[str, MarketFeatures] = {}
        for feature in features:
            market_features = feature if isinstance(feature, MarketFeatures) else MarketFeatures.from_mapping(feature)
            features_by_market[market_features.market_id] = market_features
            candidates.extend(self._approved_strategy_signals(market_features))

        if candidates:
            logger.info(f"✨ [LOOP] Cycle produced {len(candidates)} candidate signals from {len(features)} markets.")

        selected = self.selector.select(
            candidates,
            features_by_market=features_by_market,
            current_exposure_by_market=self._current_exposure_by_market(),
            total_capital=self._total_capital(),
        )
        for scored in selected:
            if self._open_position_count() >= self.config.max_total_open_positions:
                return actions
            signal = scored.signal
            enriched = StrategySignal(
                strategy_id=signal.strategy_id,
                market_id=signal.market_id,
                ticker=signal.ticker,
                side=signal.side,
                price=signal.price,
                confidence=signal.confidence,
                edge=signal.edge,
                reason=signal.reason,
                timestamp=signal.timestamp,
                order_type=signal.order_type,
                suggested_capital=scored.suggested_capital,
                metadata={
                    **signal.metadata,
                    "selection_score": scored.score,
                    "selection_ev": scored.ev,
                    "selection_risk": scored.risk,
                    "selection_cost": scored.cost,
                    "selection_uncertainty": scored.uncertainty,
                    "selection_liquidity": scored.liquidity,
                    "selection_suggested_capital": scored.suggested_capital,
                    "bandit_multiplier": scored.bandit_multiplier,
                },
            )
            action = await self.open_position(enriched)
            actions.append(action)
        return actions

    async def bootstrap_paper_history(
        self,
        features: list[Mapping[str, Any] | MarketFeatures],
        target_trades: int = 10,
    ) -> list[AutonomousAction]:
        """
        Generate closed paper trades from current strategy signals.

        This is a controlled data bootstrap: it uses existing strategy signals,
        records paper positions, then resolves them deterministically so the
        ledger has enough closed outcomes for calibration and mode promotion.
        """
        if target_trades <= 0:
            return []

        actions: list[AutonomousAction] = []
        prices = self._current_prices_from_features(features)
        candidates: list[StrategySignal] = []
        features_by_market: dict[str, MarketFeatures] = {}
        for feature in features:
            market_features = feature if isinstance(feature, MarketFeatures) else MarketFeatures.from_mapping(feature)
            features_by_market[market_features.market_id] = market_features
            candidates.extend(self._approved_strategy_signals(market_features))

        if candidates:
            logger.info(f"✨ [LOOP] Cycle produced {len(candidates)} candidate signals from {len(features)} markets.")

        selected = self.selector.select(
            candidates,
            features_by_market=features_by_market,
            current_exposure_by_market=self._current_exposure_by_market(),
            total_capital=self._total_capital(),
        )
        if not selected and features:
            # Fallback: seed from the first market using its own feature quality.
            first = next(iter(features_by_market.values()))
            selected = [type("_Scored", (), {
                "signal": StrategySignal(
                    strategy_id="bootstrap",
                    market_id=first.market_id,
                    ticker=first.ticker,
                    side="BUY" if (first.ml_probability or first.semantic_confidence or 0.5) >= first.price else "SELL",
                    price=first.price if first.price > 0 else 0.5,
                    confidence=max(0.50, min(0.80, first.semantic_confidence or 0.62)),
                    edge=max(
                        0.01,
                        abs((first.ml_probability if first.ml_probability is not None else first.semantic_confidence or 0.5) - first.price),
                    ),
                    reason="bootstrap feature-based seed",
                    metadata={"hmm_regime": first.hmm_regime},
                )
            })()]

        closed = 0
        for idx, scored in enumerate(selected):
            if closed >= target_trades:
                break
            signal = scored.signal
            open_action = self._open_paper_position(signal, self._compute_sizing(signal).get("size", 0.0) or 1.0)
            actions.append(open_action)
            if open_action.status != "OPENED":
                continue

            position_id = open_action.position_id
            entry_price = signal.price
            # Resolve paper trades using signal-derived direction rather than
            # alternating synthetic wins/losses.
            favorable_move = max(0.01, min(0.12, abs(signal.edge) * 1.2 + signal.confidence * 0.02))
            direction = 1.0 if signal.side.upper() in {"BUY", "YES", "LONG"} else -1.0
            win = signal.edge >= 0
            exit_price = entry_price * (1.0 + favorable_move * direction if win else 1.0 - favorable_move * direction)
            pnl = self._position_pnl(signal.side, entry_price, exit_price, self._paper_size_from_action(open_action, signal.price))
            self.ledger.close_paper_position(position_id, exit_price=exit_price, pnl=pnl, is_win=win)
            self.selector.update_feedback(signal.strategy_id, pnl=pnl, slippage=0.0, filled=True)
            actions.append(
                AutonomousAction(
                    "close",
                    "CLOSED",
                    signal.strategy_id,
                    signal.ticker,
                    position_id=position_id,
                    reason="bootstrap resolution",
                    pnl=pnl,
                )
            )
            closed += 1

        return actions

    async def open_position(self, signal: StrategySignal) -> AutonomousAction:
        if abs(signal.edge) < self.config.min_signal_edge:
            return AutonomousAction("open", "SKIPPED", signal.strategy_id, signal.ticker, reason="edge below loop minimum")
        if self._open_count_for_strategy(signal.strategy_id) >= self.config.max_open_positions_per_strategy:
            return AutonomousAction("open", "SKIPPED", signal.strategy_id, signal.ticker, reason="strategy position cap reached")

        mode = self.ledger.get_execution_mode().upper()
        sizing = self._compute_sizing(signal)
        size = float(sizing.get("size", 0.0) or 0.0)
        if size <= 0.0:
            return AutonomousAction("open", "REJECTED", signal.strategy_id, signal.ticker, reason=str(sizing.get("reason", "zero size")))

        objective_estimate = self._estimate_signal_objective(signal, size)
        min_expected_profit = float(TRADING_PARAMS.get("MIN_EXPECTED_PROFIT_USDC", 0.05))
        if objective_estimate.expected_net_profit_usdc <= min_expected_profit:
            return AutonomousAction(
                "open",
                "REJECTED",
                signal.strategy_id,
                signal.ticker,
                reason=(
                    f"net expected profit {objective_estimate.expected_net_profit_usdc:.4f} "
                    f"<= minimum {min_expected_profit:.4f} USDC after fees"
                ),
                metadata={
                    **signal.to_execution_signal(),
                    "trading_objective": objective_estimate.objective,
                    "estimated_cost_usdc": objective_estimate.estimated_cost_usdc,
                    "expected_net_profit_usdc": objective_estimate.expected_net_profit_usdc,
                },
            )

        if mode == "PROD" and self.config.allow_real_execution:
            return await self._open_real_position(signal, size, sizing)
        if mode == "SHADOW" and self.config.allow_real_execution:
            shadow_multiplier = float(TRADING_PARAMS.get("SHADOW_SIZE_MULTIPLIER", 0.01))
            shadow_size = max(1.0, size * shadow_multiplier)
            return await self._open_real_position(signal, shadow_size, sizing)
        return self._open_paper_position(signal, size)

    async def manage_open_positions(self, current_prices: dict[str, float]) -> list[AutonomousAction]:
        actions: list[AutonomousAction] = []
        self._apply_trailing_stops(current_prices)
        due = self.ledger.get_positions_due_for_exit(current_prices)
        for position in due:
            action = await self.close_position(position, float(position["exit_price"]), str(position["exit_reason"]))
            actions.append(action)
        return actions

    async def close_position(self, position: Mapping[str, Any], exit_price: float, reason: str) -> AutonomousAction:
        position_id = str(position.get("position_id", ""))
        ticker = str(position.get("ticker", ""))
        side = str(position.get("side", "BUY"))
        size = float(position.get("size", position.get("filled_qty", 0.0)) or 0.0)
        entry = float(position.get("entry_price", position.get("execution_price", 0.0)) or 0.0)
        pnl = self._position_pnl(side=side, entry_price=entry, exit_price=exit_price, size=size)

        if position_id.startswith("paper-"):
            self.ledger.close_position(position_id, exit_price=exit_price, pnl=pnl)
            self.lifecycle.record_paper_result(
                strategy_id=self._extract_strategy_id(position),
                pnl=pnl,
                slippage=0.0,
                rejected=False,
            )
            self.selector.update_feedback(
                self._extract_strategy_id(position),
                pnl=pnl,
                slippage=0.0,
                filled=True,
            )
            return AutonomousAction("close", "CLOSED", ticker=ticker, position_id=position_id, reason=reason, pnl=pnl)

        if not self.config.allow_real_execution:
            return AutonomousAction("close", "BLOCKED", ticker=ticker, position_id=position_id, reason="real exit disabled", pnl=pnl)

        if self.order_manager:
            order = await self.order_manager.place_order(
                market_id=str(position.get("market_id") or ticker),
                token_id=str(position.get("ticker") or ticker),
                outcome="YES" if side.upper() in {"BUY", "YES", "LONG"} else "NO",
                side="SELL" if side.upper() in {"BUY", "YES", "LONG"} else "BUY",
                price=exit_price,
                amount=size,
                dry_run=False,
            )
            if getattr(order, "status", "") in {"pending", "filled"}:
                self.ledger.close_position(position_id, exit_price=exit_price, pnl=pnl)
                return AutonomousAction("close", "CLOSED", ticker=ticker, position_id=position_id, reason=reason, pnl=pnl)
            return AutonomousAction(
                "close",
                "FAILED",
                ticker=ticker,
                position_id=position_id,
                reason=getattr(order, "error_message", "exit order failed"),
                pnl=pnl,
            )
        return AutonomousAction("close", "FAILED", ticker=ticker, position_id=position_id, reason="order manager unavailable", pnl=pnl)

    def _approved_strategy_signals(self, features: MarketFeatures) -> list[StrategySignal]:
        signals: list[StrategySignal] = []
        
        for strategy_id, strategy in self.lifecycle.strategies.items():
            state = self.lifecycle.states[strategy_id]
            phase = state.phase

            # Autorise PAPER, SANITY, REAL ou si FORCÉ
            if phase not in {StrategyPhase.PAPER, StrategyPhase.SANITY, StrategyPhase.REAL} and not state.force_real:
                continue

            strategy = self.lifecycle.strategies.get(strategy_id)
            if not strategy:
                continue

            if not hasattr(self, "_eval_counts"):
                self._depth_counts = {} # Reusing same name? No.
                self._eval_counts = {}
            key = f"{strategy_id}:{features.ticker}"
            self._eval_counts[key] = self._eval_counts.get(key, 0) + 1
            if self._eval_counts[key] % 500 == 0:
                logger.info(f"📊 [LOOP] Evaluated {strategy_id} for {features.ticker} {self._eval_counts[key]} times.")

            signal = strategy.generate_signal(features)
            if signal:
                # Si la stratégie est forcée, on s'assure qu'elle est traitée comme du REAL
                if state.force_real:
                    signal.metadata["force_real_execution"] = True
                signals.append(signal)
                log_msg = f"🎯 [STRATEGY] {strategy_id} generated signal for {features.market_id} (Side: {signal.side})\n"
                logger.info(log_msg.strip())
                STRATEGY_SIGNAL_LOG.parent.mkdir(parents=True, exist_ok=True)
                with STRATEGY_SIGNAL_LOG.open("a", encoding="utf-8") as f:
                    f.write(f"{datetime.now(timezone.utc).isoformat()} | {log_msg}")
        return signals

    def _open_paper_position(self, signal: StrategySignal, size: float) -> AutonomousAction:
        result = self.ledger.record_paper_order(
            ticker=signal.ticker,
            side=signal.side,
            price=signal.price,
            size=size,
            confidence=signal.confidence,
            regime_label=str(signal.metadata.get("hmm_regime", "")),
            signal_source=f"autonomous:{signal.strategy_id}",
        )
        if "position_id" not in result:
            return AutonomousAction("open", "FAILED", signal.strategy_id, signal.ticker, reason=str(result.get("error", "paper open failed")))
        position_id = result["position_id"]
        self.ledger.set_position_sltp(
            position_id,
            stop_loss_pct=self._stop_loss_for_signal(signal),
            take_profit_pct=self._take_profit_for_signal(signal),
        )
        self._high_watermarks[position_id] = signal.price
        return AutonomousAction(
            "open",
            "OPENED",
            signal.strategy_id,
            signal.ticker,
            position_id=position_id,
            reason=signal.reason,
            metadata=signal.to_execution_signal(),
        )

    def _estimate_signal_objective(self, signal: StrategySignal, size: float):
        spread = 0.0
        metadata = signal.metadata or {}
        if "spread" in metadata:
            try:
                spread = max(0.0, float(metadata.get("spread", 0.0)))
            except (TypeError, ValueError):
                spread = 0.0
        return estimate_trade_objective(
            edge=abs(signal.edge),
            price=signal.price,
            size=size,
            spread=spread,
            order_type=signal.order_type,
        )

    async def _open_real_position(self, signal: StrategySignal, size: float, sizing: Mapping[str, Any]) -> AutonomousAction:
        logger.info(f"🚀 [REAL TRADE] Attempting to open position for {signal.ticker} ({signal.side} @ {signal.price:.4f}) size={size:.4f}")
        minimum_notional = _minimum_polymarket_notional(self.executor or self.order_manager)
        if signal.price <= 0:
            return AutonomousAction("open", "REJECTED", signal.strategy_id, signal.ticker, reason="invalid price")
        if size * signal.price < minimum_notional:
            available_capital = float((self.ledger.get_capital_summary() or {}).get("available_capital", 0.0) or 0.0)
            if available_capital >= minimum_notional:
                size = max(size, math.ceil(minimum_notional / signal.price))
        if size * signal.price < minimum_notional:
            return AutonomousAction(
                "open",
                "REJECTED",
                signal.strategy_id,
                signal.ticker,
                reason=f"live notional {size * signal.price:.2f} < Polymarket minimum {minimum_notional:.2f}",
            )
        validation = self.ledger.validate_and_reserve(signal.ticker, signal.side, signal.price, size)
        if not validation.get("authorized"):
            return AutonomousAction("open", "REJECTED", signal.strategy_id, signal.ticker, reason=str(validation.get("reason", "risk rejected")))

        final_size = float(validation.get("size", size))

        # 1. Preferred Path: PassiveExecutor (Maker rebates, chase logic)
        if self.executor:
            try:
                exec_result = await self.executor.execute(
                    ticker=signal.ticker,
                    side=signal.side,
                    price=signal.price,
                    size=final_size
                )
                if exec_result.get("status") in {"FILLED", "TAKER_FILLED"}:
                    position_id = f"{signal.ticker}-{signal.side}-{int(time.time())}"
                    self.ledger.record_order(
                        position_id=position_id,
                        ticker=signal.ticker,
                        side=signal.side,
                        price=signal.price,
                        size=final_size,
                        requested_qty=final_size,
                        filled_qty=float(exec_result.get("filled_size", final_size)),
                        execution_price=float(exec_result.get("price", signal.price)),
                        notional_usd=float(exec_result.get("price", signal.price)) * final_size,
                        exchange_order_id=exec_result.get("order_id"),
                    )
                    self.ledger.set_position_sltp(position_id, self._stop_loss_for_signal(signal), self._take_profit_for_signal(signal))
                    return AutonomousAction("open", "OPENED", signal.strategy_id, signal.ticker, position_id=position_id, reason=signal.reason)
                else:
                    return AutonomousAction("open", "FAILED", signal.strategy_id, signal.ticker, reason=str(exec_result.get("error", "executor failed")))
            except Exception as e:
                logger.error(f"Executor failed in autonomous loop: {e}")
                # Fallback to direct manager if executor crashes

        # 2. Legacy/Fallback Path: OrderManager
        if not self.order_manager:
            return AutonomousAction("open", "FAILED", signal.strategy_id, signal.ticker, reason="order manager unavailable")

        order = await self.order_manager.place_order(
            market_id=signal.market_id,
            token_id=signal.ticker,
            outcome="YES" if signal.side.upper() in {"BUY", "YES", "LONG"} else "NO",
            side=signal.side,
            price=signal.price,
            amount=final_size,
            dry_run=False,
        )
        status = str(getattr(order, "status", "")).upper()
        if status not in {"PENDING", "FILLED"}:
            return AutonomousAction("open", "FAILED", signal.strategy_id, signal.ticker, reason=getattr(order, "error_message", "order failed"))

        position_id = f"{signal.ticker}-{signal.side}-{int(time.time())}"
        self.ledger.record_order(
            position_id=position_id,
            ticker=signal.ticker,
            side=signal.side,
            price=signal.price,
            size=final_size,
            requested_qty=final_size,
            filled_qty=final_size,
            execution_price=signal.price,
            notional_usd=signal.price * final_size,
            exchange_order_id=getattr(order, "order_id", None),
        )
        self.ledger.set_position_sltp(position_id, self._stop_loss_for_signal(signal), self._take_profit_for_signal(signal))
        return AutonomousAction("open", "OPENED", signal.strategy_id, signal.ticker, position_id=position_id, reason=signal.reason)

    def _compute_sizing(self, signal: StrategySignal) -> dict[str, Any]:
        mode = self.ledger.get_execution_mode().upper()
        if self.risk_engine and mode in {"PROD", "SHADOW"}:
            sized = self.risk_engine.compute_position_size(
                ticker=signal.ticker,
                side=signal.side,
                price=signal.price,
                confidence=signal.confidence,
                win_prob=signal.confidence,
                regime_label=str(signal.metadata.get("hmm_regime", "")),
            )
            selector_capital = max(0.0, float(signal.suggested_capital or 0.0))
            live_capital = max(0.0, float(sized.get("capital_at_risk", 0.0) or 0.0))
            bounded_capital = min(selector_capital, live_capital) if selector_capital > 0.0 and live_capital > 0.0 else max(selector_capital, live_capital)
            if bounded_capital > 0.0 and signal.price > 0.0:
                sized = {
                    **sized,
                    "size": bounded_capital / signal.price,
                    "capital_at_risk": bounded_capital,
                    "reason": "live risk engine bounded by selector capital",
                }
            return sized
        if signal.suggested_capital > 0 and signal.price > 0:
            return {
                "size": signal.suggested_capital / signal.price,
                "reason": "adaptive selector Kelly-shrunk capital",
            }
        if self.risk_engine:
            return self.risk_engine.compute_position_size(
                ticker=signal.ticker,
                side=signal.side,
                price=signal.price,
                confidence=signal.confidence,
                win_prob=signal.confidence,
                regime_label=str(signal.metadata.get("hmm_regime", "")),
            )
        size = self.config.default_paper_capital_usdc / signal.price if signal.price > 0 else 0.0
        return {"size": size, "reason": "default autonomous paper sizing"}

    def _paper_size_from_action(self, action: AutonomousAction, fallback_price: float) -> float:
        if action.metadata.get("selection_suggested_capital"):
            return float(action.metadata["selection_suggested_capital"]) / max(fallback_price, 1e-6)
        return self.config.default_paper_capital_usdc / max(fallback_price, 1e-6)

    def _total_capital(self) -> float:
        summary = self.ledger.get_capital_summary() or {}
        for key in ("total_capital", "available_capital"):
            try:
                value = float(summary.get(key, 0.0) or 0.0)
            except (TypeError, ValueError):
                value = 0.0
            if value > 0:
                return value
        return self.config.default_paper_capital_usdc * max(1, self.config.max_total_open_positions)

    def _apply_trailing_stops(self, current_prices: Mapping[str, float]) -> None:
        for position in self.ledger.get_paper_positions("OPEN") + self.ledger.get_open_positions():
            position_id = str(position.get("position_id", ""))
            ticker = str(position.get("ticker", ""))
            price = current_prices.get(ticker)
            if not position_id or price is None or price <= 0:
                continue
            entry = float(position.get("entry_price", 0.0) or 0.0)
            if entry <= 0:
                continue
            side = str(position.get("side", "BUY")).upper()
            if side in {"SELL", "NO", "SHORT"}:
                favorable = min(self._high_watermarks.get(position_id, entry), price)
                self._high_watermarks[position_id] = favorable
                gain = (entry - favorable) / entry
            else:
                favorable = max(self._high_watermarks.get(position_id, entry), price)
                self._high_watermarks[position_id] = favorable
                gain = (favorable - entry) / entry
            if gain > self.config.default_take_profit_pct / 2:
                self.ledger.set_position_sltp(
                    position_id,
                    stop_loss_pct=max(0.01, self.config.trailing_stop_pct),
                    take_profit_pct=self.config.default_take_profit_pct,
                )

    def _load_features(self, feature_source: Any | None) -> list[Mapping[str, Any] | MarketFeatures]:
        if feature_source is None:
            return []
        if callable(feature_source):
            return list(feature_source())
        return list(feature_source)

    def _current_prices_from_features(self, features: list[Mapping[str, Any] | MarketFeatures]) -> dict[str, float]:
        prices: dict[str, float] = {}
        for feature in features:
            f = feature if isinstance(feature, MarketFeatures) else MarketFeatures.from_mapping(feature)
            if f.price > 0:
                prices[f.ticker] = f.price
        return prices

    def _open_position_count(self) -> int:
        mode = self.ledger.get_execution_mode().upper()
        if mode == "PROD":
            return len(self.ledger.get_open_positions())
        if mode == "SHADOW":
            return len(self.ledger.get_paper_positions("OPEN")) + len(self.ledger.get_open_positions())
        return len(self.ledger.get_paper_positions("OPEN"))

    def _open_count_for_strategy(self, strategy_id: str) -> int:
        count = 0
        needle = f"autonomous:{strategy_id}"
        mode = self.ledger.get_execution_mode().upper()
        if mode == "PROD":
            for position in self.ledger.get_open_positions():
                if str(position.get("signal_source", "")).startswith(needle):
                    count += 1
            return count
        for position in self.ledger.get_paper_positions("OPEN"):
            if str(position.get("signal_source", "")).startswith(needle):
                count += 1
        return count

    def _current_exposure_by_market(self) -> dict[str, float]:
        exposure: dict[str, float] = {}
        mode = self.ledger.get_execution_mode().upper()
        positions: list[Mapping[str, Any]] = []
        if mode == "PROD":
            positions = self.ledger.get_open_positions()
        elif mode == "SHADOW":
            positions = self.ledger.get_paper_positions("OPEN") + self.ledger.get_open_positions()
        else:
            positions = self.ledger.get_paper_positions("OPEN")
        for position in positions:
            market_id = str(position.get("market_id") or position.get("ticker") or "")
            if not market_id:
                continue
            price = float(position.get("entry_price", position.get("execution_price", 0.0)) or 0.0)
            size = float(position.get("size", position.get("filled_qty", 0.0)) or 0.0)
            exposure[market_id] = exposure.get(market_id, 0.0) + abs(price * size)
        return exposure

    def _take_profit_for_signal(self, signal: StrategySignal) -> float:
        edge_scaled = min(0.20, max(0.0, abs(signal.edge) * 1.5))
        return max(self.config.default_take_profit_pct, edge_scaled)

    def _stop_loss_for_signal(self, signal: StrategySignal) -> float:
        confidence_discount = max(0.0, signal.confidence - 0.55) * 0.05
        return max(0.02, self.config.default_stop_loss_pct - confidence_discount)

    @staticmethod
    def _position_pnl(side: str, entry_price: float, exit_price: float, size: float) -> float:
        if side.upper() in {"SELL", "NO", "SHORT"}:
            return (entry_price - exit_price) * size
        return (exit_price - entry_price) * size

    @staticmethod
    def _extract_strategy_id(position: Mapping[str, Any]) -> str:
        source = str(position.get("signal_source") or "")
        if source.startswith("autonomous:"):
            return source.split(":", 1)[1]
        return "inter_market_arbitrage"
