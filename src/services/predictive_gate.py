from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import pandas as pd

from core.trade_objective import estimate_trade_objective
from utils.config_loader import TRADING_PARAMS

logger = logging.getLogger("PredictiveGateService")


@dataclass
class PredictiveGateConfig:
    min_edge_threshold: float = 0.07
    allow_simulated_gate: bool = False
    default_price: float = 0.5
    simulated_probability: float = 0.62
    max_spread_bps: float = 350.0
    min_obi_for_buy: float = -0.20
    max_obi_for_sell: float = 0.20
    allow_passive_only_on_wide_spread: bool = True


class PredictiveGateService:
    """
    Validates a trading signal against predictive and market-based constraints.

    The service is intentionally conservative: if no usable market features are
    present and simulation is disabled, the signal is rejected.
    """

    def __init__(
        self,
        config: dict | PredictiveGateConfig,
        model_registry: Any = None,
        feature_store: Any = None,
    ):
        if isinstance(config, dict):
            config = PredictiveGateConfig(
                min_edge_threshold=float(config.get("min_edge_threshold", 0.07)),
                allow_simulated_gate=bool(config.get("allow_simulated_gate", False)),
                default_price=float(config.get("default_price", 0.5)),
                simulated_probability=float(config.get("simulated_probability", 0.62)),
                max_spread_bps=float(config.get("max_spread_bps", 350.0)),
                min_obi_for_buy=float(config.get("min_obi_for_buy", -0.20)),
                max_obi_for_sell=float(config.get("max_obi_for_sell", 0.20)),
                allow_passive_only_on_wide_spread=bool(
                    config.get("allow_passive_only_on_wide_spread", True)
                ),
            )
        self.config = config
        self.model_registry = model_registry
        self.feature_store = feature_store

    def validate_signal(self, signal: dict) -> tuple[bool, str]:
        liquidity = self._analyze_orderbook_liquidity(signal)
        if liquidity:
            signal["microstructure_liquidity"] = liquidity
            spread_bps = float(liquidity.get("spread_bps", 0.0))
            obi = float(liquidity.get("order_imbalance", 0.0))
            side = str(signal.get("side") or signal.get("direction") or signal.get("action") or "BUY").upper()

            if spread_bps > self.config.max_spread_bps:
                signal["execution_preference"] = "PASSIVE_ONLY"
                signal["microstructure_reason"] = (
                    f"WIDE_SPREAD:{spread_bps:.1f}bps>{self.config.max_spread_bps:.1f}bps"
                )
                if not self.config.allow_passive_only_on_wide_spread:
                    return False, f"REJECT_WIDE_SPREAD:{spread_bps:.1f}bps"

            if side in {"BUY", "YES", "LONG"} and obi < self.config.min_obi_for_buy:
                return False, f"REJECT_ORDERBOOK_IMBALANCE_BUY:{obi:+.3f}"
            if side in {"SELL", "NO", "SHORT"} and obi > self.config.max_obi_for_sell:
                return False, f"REJECT_ORDERBOOK_IMBALANCE_SELL:{obi:+.3f}"

        market_features = signal.get("market_features")
        if market_features is None and liquidity:
            market_features = liquidity
            signal["market_features"] = market_features
        if market_features is None and not self.config.allow_simulated_gate:
            return False, "REJECT_NO_MARKET_FEATURES"

        try:
            predictive_engine = self._build_predictive_engine()
            if predictive_engine is None:
                if self.config.allow_simulated_gate:
                    return self._validate_simulated(signal)
                return False, "REJECT_NO_PREDICTIVE_ENGINE"

            if market_features is None:
                market_features = self._simulate_market_features()

            price = float(signal.get("price", self.config.default_price))
            timestamp_resolution = float(signal.get("timestamp_resolution", time.time() + 3600))
            ticker = str(signal.get("ticker") or signal.get("asset") or "").strip().upper()

            if hasattr(predictive_engine, "get_live_prediction") and ticker and self.feature_store is not None:
                prediction = predictive_engine.get_live_prediction(
                    ticker=ticker,
                    polymarket_frame=market_features,
                    clob_price_yes=price,
                    timestamp_resolution=timestamp_resolution,
                )
            else:
                df_market_ticks = pd.DataFrame(self._normalize_market_feature_rows(market_features))
                prediction = predictive_engine.predict_winning_bet(
                    df_market_ticks=df_market_ticks,
                    clob_price_yes=price,
                    timestamp_resolution=timestamp_resolution,
                    ticker=ticker,
                )
            if not prediction.get("pari_approuve"):
                edge = float(prediction.get("absolute_edge", 0.0))
                signal["predictive_edge"] = edge
                signal["predictive_probability"] = float(prediction.get("probability_win", 0.0))
                signal["fair_probability_yes"] = float(prediction.get("probability_win", 0.0))
                signal["gross_edge"] = edge
                return False, f"REJECT_NO_EDGE:{edge:+.4f}"

            spread_value = 0.0
            if liquidity:
                spread_bps = float(liquidity.get("spread_bps", 0.0))
                mid_price = max(0.0, float(liquidity.get("mid_price", price) or price))
                spread_value = mid_price * spread_bps / 10_000.0
            objective_size = self._resolve_trade_objective_size(signal, price)
            estimate = estimate_trade_objective(
                edge=float(prediction.get("absolute_edge", 0.0)),
                price=price,
                size=objective_size,
                spread=spread_value,
                order_type=str(signal.get("order_type", "LIMIT")),
            )
            net_edge = estimate.expected_net_profit_usdc
            min_net_profit = float(TRADING_PARAMS.get("MIN_EXPECTED_PROFIT_USDC", 0.05))
            if net_edge <= min_net_profit:
                signal["fair_probability_yes"] = float(prediction.get("probability_win", 0.0))
                signal["gross_edge"] = float(prediction.get("absolute_edge", 0.0))
                signal["predictive_net_edge"] = net_edge
                signal["predictive_estimated_cost"] = estimate.estimated_cost_usdc
                signal["predictive_effective_size"] = objective_size
                signal["predictive_objective_reason"] = self._classify_net_edge_rejection(
                    signal=signal,
                    net_edge=net_edge,
                    min_net_profit=min_net_profit,
                    estimate=estimate,
                )
                return False, f"REJECT_NO_NET_EDGE:{net_edge:+.4f}"

            signal["predictive_probability"] = float(prediction.get("probability_win", 0.0))
            signal["fair_probability_yes"] = float(prediction.get("probability_win", 0.0))
            signal["predictive_edge"] = float(prediction.get("absolute_edge", 0.0))
            signal["gross_edge"] = float(prediction.get("absolute_edge", 0.0))
            signal["predictive_net_edge"] = net_edge
            signal["predictive_estimated_cost"] = estimate.estimated_cost_usdc
            signal["predictive_effective_size"] = objective_size
            signal["trading_objective"] = estimate.objective
            if liquidity:
                signal["predictive_spread_bps"] = float(liquidity.get("spread_bps", 0.0))
                signal["predictive_order_imbalance"] = float(liquidity.get("order_imbalance", 0.0))
            return True, "ACCEPT_PREDICTIVE_EDGE"
        except Exception as exc:
            logger.warning("Predictive gate failed, rejecting signal: %s", exc)
            if self.config.allow_simulated_gate:
                return self._validate_simulated(signal)
            return False, f"REJECT_ERROR:{exc}"

    def _analyze_orderbook_liquidity(self, signal: dict) -> dict[str, float]:
        market_features = signal.get("market_features")
        normalized = self._normalize_liquidity_features(market_features)
        if normalized:
            return normalized

        feature_store = self._feature_store_from_signal(signal)
        token_id = self._extract_token_id(signal)
        if not feature_store or not token_id:
            return {}

        try:
            events = feature_store.get_web_events(event_type="orderbook_snapshot", limit=200)
        except Exception as exc:
            logger.debug("Microstructure lookup unavailable: %s", exc)
            return {}

        for event in reversed(events):
            raw = event.get("raw") or {}
            if not isinstance(raw, dict):
                continue
            raw_token = str(raw.get("token_id", raw.get("asset_id", raw.get("token", "")))).strip()
            raw_market = str(raw.get("market", raw.get("condition_id", ""))).strip()
            if token_id and token_id not in {raw_token, raw_market}:
                continue
            normalized = self._normalize_liquidity_features(raw)
            if normalized:
                return normalized
        return {}

    def _normalize_liquidity_features(self, features: Any) -> dict[str, float]:
        if not features:
            return {}
        if isinstance(features, list):
            if not features:
                return {}
            features = features[-1]
        if not isinstance(features, dict):
            return {}

        spread_bps = features.get("spread_bps", features.get("spread", 0.0))
        # Convert fractional spreads (e.g. 0.0012 == 12 bps), but keep values
        # already expressed in basis points untouched (e.g. 10.0, 120.0).
        if spread_bps and float(spread_bps) <= 1.0:
            spread_bps = float(spread_bps) * 10_000.0

        obi = features.get("order_imbalance", features.get("orderbook_imbalance", 0.0))
        bid_depth = features.get("bid_depth_3", features.get("bid_depth", 0.0))
        ask_depth = features.get("ask_depth_3", features.get("ask_depth", 0.0))
        mid_price = features.get("mid_price", features.get("mid", features.get("price", 0.0)))

        try:
            spread_bps_f = float(spread_bps)
            obi_f = float(obi)
            bid_f = float(bid_depth)
            ask_f = float(ask_depth)
            mid_f = float(mid_price)
        except (TypeError, ValueError):
            return {}

        return {
            "spread_bps": spread_bps_f,
            "order_imbalance": obi_f,
            "bid_depth_3": bid_f,
            "ask_depth_3": ask_f,
            "mid_price": mid_f,
        }

    def _normalize_market_feature_rows(self, features: Any) -> list[dict[str, Any]]:
        if features is None:
            return []
        if isinstance(features, list):
            if not features:
                return []
            if all(isinstance(row, dict) for row in features):
                return features
            return [{"value": row} for row in features]
        if isinstance(features, dict):
            if any(isinstance(value, list) for value in features.values()):
                keys = list(features.keys())
                max_len = max(
                    (len(value) for value in features.values() if isinstance(value, list)),
                    default=0,
                )
                rows: list[dict[str, Any]] = []
                for idx in range(max_len or 1):
                    row: dict[str, Any] = {}
                    for key in keys:
                        value = features[key]
                        if isinstance(value, list):
                            row[key] = value[idx] if idx < len(value) else value[-1] if value else None
                        else:
                            row[key] = value
                    rows.append(row)
                return rows
            return [features]
        return [{"value": features}]

    def _feature_store_from_signal(self, signal: dict) -> Any:
        for key in ("feature_store", "store"):
            store = signal.get(key)
            if store is not None:
                return store
        if self.feature_store is not None:
            return self.feature_store
        return self.model_registry if hasattr(self.model_registry, "get_web_events") else None

    def _extract_token_id(self, signal: dict) -> str:
        raw = str(signal.get("token_id") or signal.get("asset") or signal.get("ticker") or "").strip()
        return raw

    def _build_predictive_engine(self) -> Any:
        if self.model_registry is None:
            return None
        if hasattr(self.model_registry, "predict_winning_bet"):
            return self.model_registry
        if callable(self.model_registry):
            return self.model_registry()
        return None

    def _simulate_market_features(self) -> dict[str, list[float]]:
        return {
            "price": [self.config.default_price],
            "volume": [100.0],
            "bid_depth": [50.0],
            "ask_depth": [50.0],
        }

    def _validate_simulated(self, signal: dict) -> tuple[bool, str]:
        simulated_edge = float(signal.get("simulated_edge", 0.0))
        if simulated_edge >= self.config.min_edge_threshold:
            signal["predictive_probability"] = self.config.simulated_probability
            signal["predictive_edge"] = simulated_edge
            return True, "ACCEPT_SIMULATED_EDGE"
        return False, "REJECT_SIMULATED_EDGE"

    def _resolve_trade_objective_size(self, signal: dict, price: float) -> float:
        explicit_size = float(signal.get("size", 0.0) or 0.0)
        if explicit_size > 0.0:
            return explicit_size

        explicit_notional = float(signal.get("target_notional_usdc", 0.0) or 0.0)
        if explicit_notional <= 0.0:
            explicit_notional = float(
                TRADING_PARAMS.get(
                    "MAX_REAL_NOTIONAL_USDC",
                    TRADING_PARAMS.get("FALLBACK_CAPITAL_USDC", 1.0),
                )
            )
        if explicit_notional <= 0.0:
            explicit_notional = 1.0
        return max(explicit_notional / max(price, 1e-6), 1.0)

    @staticmethod
    def _classify_net_edge_rejection(
        *,
        signal: dict,
        net_edge: float,
        min_net_profit: float,
        estimate: Any,
    ) -> str:
        if float(signal.get("size", 0.0) or 0.0) <= 0.0:
            return (
                "REJECT_COST_MODEL_MISMATCH"
                if net_edge > 0.0 and net_edge < min_net_profit
                else "REJECT_NO_NET_EDGE"
            )
        if estimate.estimated_cost_usdc >= estimate.expected_gross_profit_usdc:
            return "REJECT_ESTIMATED_COST_EXCEEDS_GROSS"
        return "REJECT_NO_NET_EDGE"
