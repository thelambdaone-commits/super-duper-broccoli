from __future__ import annotations

import json
import math
import random
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from user_data.strategies.base_strategy import MarketFeatures, StrategySignal
from utils.config_loader import TRADING_PARAMS


@dataclass
class StrategySelectionConfig:
    _s = TRADING_PARAMS.get("SELECTION", {})
    risk_lambda: float = float(_s.get("risk_lambda", 1.0))
    cost_mu: float = float(_s.get("cost_mu", 1.0))
    time_gamma: float = float(_s.get("time_gamma", 0.15))
    min_score: float = 0.0
    top_k: int = 3
    exploration_rate: float = 0.10
    max_market_exposure_penalty: float = 0.20
    ev_min: float = float(_s.get("ev_min", 0.005))
    sigma_relative_max: float = 0.20
    min_liquidity_usdc: float = 25.0
    max_cost: float = float(_s.get("max_cost", 0.04))
    min_time_to_settlement_hours: float = 0.25
    max_time_to_settlement_hours: float = 24.0 * 365.0
    max_concurrent_markets: int = 3
    max_new_positions_per_cycle: int = 1
    max_capital_per_market_pct: float = 0.05
    small_explore_pct: float = 0.10
    kelly_shrinkage: float = 0.30
    absolute_trade_capital_usdc: float = float(_s.get("absolute_trade_capital_usdc", 25.0))
    correlation_threshold: float = 0.85
    prefer_post_only: bool = True
    bandit_state_path: str = "user_data/data/strategy_bandit_state.json"


@dataclass(frozen=True)
class StrategyScore:
    signal: StrategySignal
    score: float
    ev: float
    risk: float
    cost: float
    time_to_settlement_hours: float
    bandit_multiplier: float
    liquidity: float = 0.0
    uncertainty: float = 0.0
    suggested_capital: float = 0.0
    penalties: dict[str, float] = field(default_factory=dict)


@dataclass
class BanditArmState:
    alpha: float = 1.0
    beta: float = 1.0
    reward_sum: float = 0.0
    pulls: int = 0
    last_update: float = field(default_factory=time.time)

    @property
    def mean(self) -> float:
        total = self.alpha + self.beta
        return self.alpha / total if total > 0 else 0.5


class StrategyBandit:
    def __init__(self, state_path: str) -> None:
        self.state_path = Path(state_path)
        self.arms: dict[str, BanditArmState] = {}
        self._load()

    def multiplier(self, arm_id: str, exploration_rate: float = 0.10) -> float:
        state = self._arm(arm_id)
        if random.random() < max(0.0, min(1.0, exploration_rate)):
            sample = random.betavariate(state.alpha, state.beta)
        else:
            sample = state.mean
        base = TRADING_PARAMS["BANDIT_MULTIPLIER_BASE"]
        rng = TRADING_PARAMS["BANDIT_MULTIPLIER_RANGE"]
        return base + sample * rng

    def update(self, arm_id: str, pnl: float, slippage: float = 0.0, filled: bool = True) -> None:
        state = self._arm(arm_id)
        reward = float(pnl) - abs(float(slippage))
        agg = TRADING_PARAMS["BANDIT_AGGRESSIVENESS"]
        if filled and reward > 0:
            state.alpha += min(agg, 1.0 + reward)
        else:
            state.beta += min(agg, 1.0 + abs(reward))
        state.reward_sum += reward
        state.pulls += 1
        state.last_update = time.time()
        self.persist()

    def persist(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {arm: asdict(state) for arm, state in self.arms.items()}
        self.state_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def _arm(self, arm_id: str) -> BanditArmState:
        if arm_id not in self.arms:
            self.arms[arm_id] = BanditArmState()
        return self.arms[arm_id]

    def _load(self) -> None:
        if not self.state_path.exists():
            return
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            return
        for arm, raw in payload.items():
            try:
                self.arms[arm] = BanditArmState(**raw)
            except TypeError:
                continue


class StrategySelector:
    def __init__(
        self,
        config: StrategySelectionConfig | None = None,
        bandit: StrategyBandit | None = None,
    ) -> None:
        self.config = config or StrategySelectionConfig()
        self.bandit = bandit or StrategyBandit(self.config.bandit_state_path)

    def rank(
        self,
        signals: Iterable[StrategySignal],
        features_by_market: Mapping[str, MarketFeatures] | None = None,
        current_exposure_by_market: Mapping[str, float] | None = None,
        total_capital: float | None = None,
    ) -> list[StrategyScore]:
        features_by_market = features_by_market or {}
        exposure = current_exposure_by_market or {}
        scored = [
            self.score_signal(
                signal,
                features_by_market.get(signal.market_id),
                exposure.get(signal.market_id, 0.0),
                total_capital=total_capital,
            )
            for signal in signals
        ]
        scored = [score for score in scored if self._passes_quality_filters(score, exposure, total_capital)]
        return sorted(
            [score for score in scored if score.score > self.config.min_score],
            key=lambda item: item.score,
            reverse=True,
        )

    def select(
        self,
        signals: Iterable[StrategySignal],
        features_by_market: Mapping[str, MarketFeatures] | None = None,
        current_exposure_by_market: Mapping[str, float] | None = None,
        total_capital: float | None = None,
    ) -> list[StrategyScore]:
        ranked = self.rank(signals, features_by_market, current_exposure_by_market, total_capital=total_capital)
        slots = max(0, int(self.config.max_concurrent_markets) - len(set((current_exposure_by_market or {}).keys())))
        limit = max(0, min(int(self.config.top_k), int(self.config.max_new_positions_per_cycle), slots if slots > 0 else int(self.config.top_k)))
        selected: list[StrategyScore] = []
        selected_markets: set[str] = set()
        selected_groups: set[str] = set()
        for score in ranked:
            if len(selected) >= limit:
                break
            group = _correlation_group(score.signal)
            if score.signal.market_id in selected_markets:
                continue
            if group and group in selected_groups:
                continue
            selected.append(score)
            selected_markets.add(score.signal.market_id)
            if group:
                selected_groups.add(group)
        return selected

    def score_signal(
        self,
        signal: StrategySignal,
        features: MarketFeatures | None = None,
        market_exposure: float = 0.0,
        total_capital: float | None = None,
    ) -> StrategyScore:
        metadata = signal.metadata or {}
        time_to_settlement = _positive_float(metadata.get("time_to_settlement_hours"), 24.0)
        probability = _probability_estimate(signal, features)
        payout_ev = _position_ev(signal, probability)
        cost = _execution_cost(signal, features)
        risk = _risk_estimate(signal, features)
        uncertainty = _uncertainty_estimate(signal, probability)
        liquidity = _liquidity_estimate(features)
        concentration_penalty = min(
            self.config.max_market_exposure_penalty,
            max(0.0, float(market_exposure)) * 0.01,
        )
        bandit_multiplier = self.bandit.multiplier(signal.strategy_id, self.config.exploration_rate)
        time_discount = max(1.0, time_to_settlement ** self.config.time_gamma)
        liquidity_factor = min(2.0, liquidity / max(self.config.min_liquidity_usdc, 1e-6))
        ev_quality = (payout_ev / max(uncertainty, 1e-6)) * liquidity_factor / max(cost, 1e-4)
        penalty = self.config.risk_lambda * risk + self.config.cost_mu * cost + concentration_penalty
        raw_score = (ev_quality - penalty) / time_discount
        final_score = raw_score * bandit_multiplier
        return StrategyScore(
            signal=signal,
            score=float(final_score),
            ev=float(payout_ev),
            risk=float(risk),
            cost=float(cost),
            time_to_settlement_hours=float(time_to_settlement),
            bandit_multiplier=float(bandit_multiplier),
            liquidity=float(liquidity),
            uncertainty=float(uncertainty),
            suggested_capital=float(self._suggest_capital(signal, payout_ev, risk, total_capital)),
            penalties={
                "concentration": concentration_penalty,
                "risk": self.config.risk_lambda * risk,
                "cost": self.config.cost_mu * cost,
                "liquidity_factor": liquidity_factor,
            },
        )

    def update_feedback(self, strategy_id: str, pnl: float, slippage: float = 0.0, filled: bool = True) -> None:
        self.bandit.update(strategy_id, pnl=pnl, slippage=slippage, filled=filled)

    def _passes_quality_filters(
        self,
        score: StrategyScore,
        current_exposure_by_market: Mapping[str, float],
        total_capital: float | None,
    ) -> bool:
        if score.ev < self.config.ev_min:
            return False
        if score.uncertainty > self.config.sigma_relative_max:
            return False
        if score.liquidity < self.config.min_liquidity_usdc:
            return False
        if score.cost > self.config.max_cost:
            return False
        if score.time_to_settlement_hours < self.config.min_time_to_settlement_hours:
            return False
        if score.time_to_settlement_hours > self.config.max_time_to_settlement_hours:
            return False
        if self.config.prefer_post_only and score.signal.order_type.upper() == "MARKET":
            if score.ev < self.config.ev_min * 3.0:
                return False
        if total_capital and total_capital > 0:
            exposure = float(current_exposure_by_market.get(score.signal.market_id, 0.0) or 0.0)
            if exposure >= total_capital * self.config.max_capital_per_market_pct:
                return False
        return True

    def _suggest_capital(self, signal: StrategySignal, ev: float, risk: float, total_capital: float | None) -> float:
        if not total_capital or total_capital <= 0:
            return min(self.config.absolute_trade_capital_usdc, max(0.0, signal.suggested_capital))
        kelly_estimate = max(0.0, ev / max(risk, 1e-6))
        shrunk_kelly = min(self.config.max_capital_per_market_pct, kelly_estimate * self.config.kelly_shrinkage)
        capital = total_capital * shrunk_kelly
        return min(self.config.absolute_trade_capital_usdc, max(0.0, capital))


def _probability_estimate(signal: StrategySignal, features: MarketFeatures | None) -> float:
    for key in ("estimated_probability", "posterior_probability", "monte_carlo_probability", "ml_probability"):
        if key in signal.metadata:
            return max(0.01, min(0.99, _positive_float(signal.metadata[key], signal.confidence)))
    if features and features.ml_probability is not None:
        return max(0.01, min(0.99, features.ml_probability))
    if signal.side.upper() in {"SELL", "NO", "SHORT"}:
        return max(0.01, min(0.99, 1.0 - signal.price + abs(signal.edge)))
    return max(0.01, min(0.99, signal.price + abs(signal.edge)))


def _position_ev(signal: StrategySignal, probability: float) -> float:
    price = max(0.01, min(0.99, signal.price))
    if signal.side.upper() in {"SELL", "NO", "SHORT"}:
        return (1.0 - probability) * price - probability * (1.0 - price)
    return probability * (1.0 - price) - (1.0 - probability) * price


def _execution_cost(signal: StrategySignal, features: MarketFeatures | None) -> float:
    fee = _positive_float(signal.metadata.get("fee_slippage_cost"), 0.0)
    spread = features.spread if features else _positive_float(signal.metadata.get("spread"), 0.0)
    order_penalty = 0.004 if signal.order_type.upper() == "MARKET" else 0.001
    return max(0.0, fee + spread * 0.5 + order_penalty)


def _risk_estimate(signal: StrategySignal, features: MarketFeatures | None) -> float:
    variance = _positive_float(signal.metadata.get("probability_variance"), 0.0)
    if variance <= 0.0:
        variance = max(0.0025, signal.confidence * (1.0 - signal.confidence) * 0.10)
    liquidity_penalty = 0.0
    if features:
        depth = max(0.0, features.bid_volume + features.ask_volume)
        liquidity_penalty = 0.02 if depth <= 0 else min(0.02, 1.0 / (depth + 1.0))
    return max(0.0, math.sqrt(max(0.0, variance)) + liquidity_penalty)


def _uncertainty_estimate(signal: StrategySignal, probability: float) -> float:
    metadata = signal.metadata or {}
    if "sigma_relative" in metadata:
        return _positive_float(metadata["sigma_relative"], 1.0)
    variance = _positive_float(metadata.get("probability_variance"), 0.0)
    if variance > 0:
        return math.sqrt(variance) / max(0.01, probability)
    return max(0.0, min(1.0, 1.0 - float(signal.confidence)))


def _liquidity_estimate(features: MarketFeatures | None) -> float:
    if features is None:
        return 0.0
    if "liquidity_usdc" in features.metadata:
        return _positive_float(features.metadata["liquidity_usdc"], 0.0)
    depth = max(0.0, features.bid_volume + features.ask_volume)
    price = max(0.01, features.price)
    return depth * price


def _correlation_group(signal: StrategySignal) -> str:
    group = signal.metadata.get("correlation_group") if signal.metadata else None
    return str(group or signal.market_id or signal.ticker)


def _positive_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        return default
    return max(0.0, parsed)
