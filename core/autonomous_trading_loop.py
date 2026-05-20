from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from core.autonomous_mode_controller import AutonomousModeController
from core.strategy_lifecycle_manager import StrategyLifecycleManager, StrategyPhase
from core.strategy_selector import StrategySelectionConfig, StrategySelector
from ledger.ledger_db import Ledger
from user_data.strategies.base_strategy import MarketFeatures, StrategySignal
from utils.feature_store import FeatureStore

logger = logging.getLogger("AutonomousTradingLoop")


class PriceProvider(Protocol):
    def get_prices(self) -> dict[str, float]:
        ...


@dataclass
class AutonomousTradingConfig:
    mode: str = "PAPER"
    poll_interval_seconds: float = 5.0
    default_take_profit_pct: float = 0.12
    default_stop_loss_pct: float = 0.06
    trailing_stop_pct: float = 0.04
    min_signal_edge: float = 0.02
    max_open_positions_per_strategy: int = 3
    max_total_open_positions: int = 12
    default_paper_capital_usdc: float = 10.0
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
    ) -> None:
        self.ledger = ledger
        self.lifecycle = lifecycle or StrategyLifecycleManager()
        self.risk_engine = risk_engine
        self.feature_store = feature_store
        self.price_provider = price_provider
        self.order_manager = order_manager
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

        if mode == "PROD" and self.config.allow_real_execution:
            return await self._open_real_position(signal, size, sizing)
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
            phase = self.lifecycle.states[strategy_id].phase
            if phase not in {StrategyPhase.PAPER, StrategyPhase.SANITY, StrategyPhase.REAL}:
                continue
            signal = strategy.generate_signal(features)
            if signal:
                signals.append(signal)
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

    async def _open_real_position(self, signal: StrategySignal, size: float, sizing: Mapping[str, Any]) -> AutonomousAction:
        validation = self.ledger.validate_and_reserve(signal.ticker, signal.side, signal.price, size)
        if not validation.get("authorized"):
            return AutonomousAction("open", "REJECTED", signal.strategy_id, signal.ticker, reason=str(validation.get("reason", "risk rejected")))
        if not self.order_manager:
            return AutonomousAction("open", "FAILED", signal.strategy_id, signal.ticker, reason="order manager unavailable")

        final_size = float(validation.get("size", size))
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
        return len(self.ledger.get_paper_positions("OPEN")) + len(self.ledger.get_open_positions())

    def _open_count_for_strategy(self, strategy_id: str) -> int:
        count = 0
        needle = f"autonomous:{strategy_id}"
        for position in self.ledger.get_paper_positions("OPEN"):
            if str(position.get("signal_source", "")).startswith(needle):
                count += 1
        return count

    def _current_exposure_by_market(self) -> dict[str, float]:
        exposure: dict[str, float] = {}
        for position in self.ledger.get_paper_positions("OPEN") + self.ledger.get_open_positions():
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
