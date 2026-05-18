from __future__ import annotations

import logging
import math
import time
from dataclasses import asdict, dataclass
from typing import Any, Optional

from utils.feature_store import FeatureStore
from utils.market_scanner import MarketScanner

logger = logging.getLogger("LobstarCognitiveBrain")


@dataclass(frozen=True)
class LobstarCognitiveDecision:
    ticker: str
    side: str
    past_order_imbalance_avg: float
    present_orderbook_imbalance: float
    future_time_decay_probability: float
    fused_score: float
    confidence: float
    action: str
    reason: str
    arbitrage_edge: float = 0.0
    legging_risk_score: float = 0.0
    kolmogorov_spread: float = 0.0
    microstructure_regime: str = "UNKNOWN"
    take_profit_bias: float = 0.0
    stop_loss_bias: float = 0.0
    spread_bps: float = 0.0
    order_imbalance: float = 0.0
    observed_liquidity_score: float = 0.0


class LobstarCognitiveBrain:
    """
    Past/Present/Future decision layer:
    - Past: average DuckDB order imbalance.
    - Present: current CLOB book imbalance.
    - Future: calibrated probability damped by time decay.
    """

    def __init__(
        self,
        store: Optional[FeatureStore],
        scanner: Optional[MarketScanner],
        training_pipeline: Any = None,
        arbitrage_engine: Optional[Any] = None,
        oi_lookback_seconds: int = 1800,
        time_decay_half_life_seconds: int = 3600,
    ) -> None:
        self.store = store
        self.scanner = scanner
        self.training_pipeline = training_pipeline
        self.arbitrage_engine = arbitrage_engine
        self.oi_lookback_seconds = max(1, int(oi_lookback_seconds))
        self.time_decay_half_life_seconds = max(1, int(time_decay_half_life_seconds))

    async def synthetiser_decision_decision(self, signal: dict[str, Any]) -> LobstarCognitiveDecision:
        ticker = self._extract_ticker(signal)
        side = self._extract_side(signal)
        past_oi = self._past_order_imbalance_avg(ticker)
        present_imbalance = self._present_orderbook_imbalance(ticker, side)
        future_prob = self._future_time_decay_probability(ticker, signal)
        microstructure = self._extract_microstructure_context(signal)
        microstructure_bias = self._microstructure_bias(side, microstructure)
        liquidity_score = self._compute_observed_liquidity_score(microstructure)

        # Fused Arbitrage Logic
        arb_edge = 0.0
        legging_risk = 0.0
        kolmogorov_spread = 0.0

        if self.arbitrage_engine:
            # 1. Check Kolmogorov anomalies
            outcomes = signal.get("outcomes")
            if outcomes:
                kolm_report = self.arbitrage_engine.detecter_anomalie_kolmogorov(outcomes)
                if kolm_report and kolm_report.get("detected"):
                    kolmogorov_spread = kolm_report.get("spread", 0.0)
                    arb_edge = max(arb_edge, kolm_report.get("theoretical_edge", 0.0))

            # 2. Check cross-market arbitrage
            primary_outcome = signal.get("primary_outcome")
            secondary_markets = signal.get("secondary_markets")
            if primary_outcome is not None and secondary_markets is not None:
                cross_arb = self.arbitrage_engine.detecter_arbitrage_cross_market(
                    ticker, primary_outcome, secondary_markets
                )
                if cross_arb:
                    arb_edge = max(arb_edge, cross_arb.theoretical_spread)

            # 3. Check legging risk
            panier_contrats = signal.get("panier_contrats")
            if panier_contrats:
                risk_report = self.arbitrage_engine.evaluer_legging_risk(panier_contrats)
                legging_risk = float(risk_report.get("liquidity_risk_score", 0.0))
                if not risk_report.get("authorized"):
                    legging_risk = max(legging_risk, 1.0)

        directional_sign = 1.0 if side in {"BUY", "YES", "LONG"} else -1.0
        past_component = directional_sign * past_oi
        present_component = directional_sign * present_imbalance
        future_component = (future_prob - 0.5) * 2.0

        if arb_edge > 0.0:
            # Shift weight to the arbitrage edge when it exists
            fused_score = (
                0.20 * past_component
                + 0.20 * present_component
                + 0.20 * future_component
                + 0.40 * (arb_edge * 5.0)
            )
        else:
            fused_score = (
                0.30 * past_component
                + 0.30 * present_component
                + 0.40 * future_component
            )

        # Apply legging risk penalty
        if legging_risk > 0.0:
            fused_score -= 0.5 * legging_risk
        fused_score += 0.15 * microstructure_bias["score_bias"]

        fused_score = self._clip(fused_score)
        confidence = max(
            0.0,
            min(
                0.99,
                0.5
                + abs(fused_score) / 2.0
                + 0.05 * abs(microstructure_bias["score_bias"]),
            ),
        )

        if legging_risk >= 0.8:
            action = "FADE"
        else:
            action = "EXECUTE" if fused_score >= 0.0 else "FADE"

        reason = (
            f"past_oi={past_oi:+.4f}; present_book={present_imbalance:+.4f}; "
            f"future_decay_prob={future_prob:.4f}; "
        )
        if arb_edge > 0.0:
            reason += f"arb_edge={arb_edge:+.4f}; "
        if legging_risk > 0.0:
            reason += f"legging_risk={legging_risk:.2f}; "
        if microstructure_bias["regime"] != "UNKNOWN":
            reason += (
                f"microstructure={microstructure_bias['regime']}; "
                f"spread_bps={microstructure_bias['spread_bps']:.2f}; "
                f"obi={microstructure_bias['order_imbalance']:+.4f}; "
            )
        reason += f"fused={fused_score:+.4f}"

        return LobstarCognitiveDecision(
            ticker=ticker,
            side=side,
            past_order_imbalance_avg=past_oi,
            present_orderbook_imbalance=present_imbalance,
            future_time_decay_probability=future_prob,
            fused_score=fused_score,
            confidence=confidence,
            action=action,
            reason=reason,
            arbitrage_edge=arb_edge,
            legging_risk_score=legging_risk,
            kolmogorov_spread=kolmogorov_spread,
            microstructure_regime=microstructure_bias["regime"],
            take_profit_bias=microstructure_bias["take_profit_bias"],
            stop_loss_bias=microstructure_bias["stop_loss_bias"],
            spread_bps=microstructure_bias["spread_bps"],
            order_imbalance=microstructure_bias["order_imbalance"],
            observed_liquidity_score=liquidity_score,
        )

    async def synthesize_cognitive_decision(self, signal: dict[str, Any]) -> LobstarCognitiveDecision:
        return await self.synthetiser_decision_decision(signal)

    def enrich_signal(
        self,
        signal: dict[str, Any],
        decision: LobstarCognitiveDecision,
    ) -> dict[str, Any]:
        enriched = dict(signal)
        decision_payload = asdict(decision)
        enriched["cognitive_decision"] = decision_payload
        enriched["cognitive_confidence"] = decision.confidence
        enriched["calibrated_prob_time_decay"] = decision.future_time_decay_probability
        enriched["cognitive_fused_score"] = decision.fused_score
        enriched["cognitive_action"] = decision.action
        enriched["microstructure_regime"] = decision.microstructure_regime
        enriched["take_profit_bias"] = decision.take_profit_bias
        enriched["stop_loss_bias"] = decision.stop_loss_bias
        enriched["spread_bps"] = decision.spread_bps
        enriched["order_imbalance"] = decision.order_imbalance
        enriched["observed_liquidity_score"] = decision.observed_liquidity_score
        return enriched

    def _extract_ticker(self, signal: dict[str, Any]) -> str:
        raw = str(
            signal.get("asset")
            or signal.get("ticker")
            or signal.get("token_id")
            or signal.get("market_slug")
            or ""
        ).strip()
        return raw if raw.lower().startswith("0x") else raw.upper()

    def _extract_side(self, signal: dict[str, Any]) -> str:
        side = str(signal.get("action") or signal.get("side") or "BUY").strip().upper()
        if side in {"NO", "SHORT"}:
            return "SELL"
        if side in {"YES", "LONG"}:
            return "BUY"
        return side or "BUY"

    def _past_order_imbalance_avg(self, ticker: str) -> float:
        if not self.store or not ticker:
            return 0.0

        now = time.time()
        try:
            rows = self.store.get_microstructure_range(now - self.oi_lookback_seconds, now, ticker)
            values = [
                float(row.get("order_imbalance") or 0.0)
                for row in rows
                if row.get("order_imbalance") is not None
            ]
            if values:
                return self._clip(sum(values) / len(values))

            feature_rows = self.store.get_feature_history(
                ticker,
                "oi_5min",
                since_ts=now - self.oi_lookback_seconds,
                limit=1000,
            )
            feature_values = [float(row.get("value") or 0.0) for row in feature_rows]
            if feature_values:
                return self._clip(sum(feature_values) / len(feature_values))
        except Exception as exc:
            logger.debug("Past order imbalance unavailable for %s: %s", ticker, exc)
        return 0.0

    def _present_orderbook_imbalance(self, ticker: str, side: str) -> float:
        if not self.scanner or not ticker:
            return 0.0

        try:
            token_id = ticker if ticker.lower().startswith("0x") else self.scanner.resolve_ticker_to_token_id(ticker, side)
            if not token_id:
                return 0.0
            book = self.scanner.client.get_order_book(token_id)
            bid_volume = sum(level.size for level in book.bids[:5])
            ask_volume = sum(level.size for level in book.asks[:5])
            total = bid_volume + ask_volume
            if total <= 0:
                return 0.0
            return self._clip((bid_volume - ask_volume) / total)
        except Exception as exc:
            logger.debug("Present order book unavailable for %s: %s", ticker, exc)
            return 0.0

    def _future_time_decay_probability(self, ticker: str, signal: dict[str, Any]) -> float:
        probability = self._extract_probability(signal)
        if probability is None and self.training_pipeline and ticker:
            try:
                features = self.training_pipeline.latest_features_as_vector(ticker)
                prediction = self.training_pipeline.predict(ticker, features) if features is not None else None
                if prediction:
                    probability = float(prediction.get("prob_up", 0.5))
            except Exception as exc:
                logger.debug("Future calibrated probability unavailable for %s: %s", ticker, exc)

        probability = 0.5 if probability is None else max(0.0, min(1.0, float(probability)))
        signal_ts = self._extract_timestamp(signal)
        age_seconds = max(0.0, time.time() - signal_ts)
        decay = math.exp(-math.log(2.0) * age_seconds / self.time_decay_half_life_seconds)
        return 0.5 + (probability - 0.5) * decay

    def _extract_probability(self, signal: dict[str, Any]) -> Optional[float]:
        for key in ("calibrated_prob", "calibrated_probability", "probability", "confidence"):
            value = signal.get(key)
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return None
        return None

    def _extract_timestamp(self, signal: dict[str, Any]) -> float:
        value = signal.get("timestamp") or signal.get("ts")
        if value is None:
            return time.time()
        try:
            return float(value)
        except (TypeError, ValueError):
            return time.time()

    def _extract_microstructure_context(self, signal: dict[str, Any]) -> dict[str, float | str]:
        raw = signal.get("microstructure_context") or signal.get("order_book_metrics") or {}
        if not isinstance(raw, dict):
            return {}
        spread = raw.get("spread_bps", raw.get("spread", 0.0))
        imbalance = raw.get("order_imbalance", raw.get("obi", 0.0))
        liquidity = raw.get("liquidity_score", raw.get("volume_score", raw.get("market_liquidity", 0.0)))
        regime = str(raw.get("regime") or raw.get("liquidity_regime") or "UNKNOWN").upper()
        try:
            return {
                "spread_bps": float(spread or 0.0),
                "order_imbalance": float(imbalance or 0.0),
                "liquidity_score": float(liquidity or 0.0),
                "regime": regime,
            }
        except (TypeError, ValueError):
            return {"regime": regime}

    def _compute_observed_liquidity_score(self, microstructure: dict[str, Any]) -> float:
        spread_bps = float(microstructure.get("spread_bps") or 0.0)
        order_imbalance = float(microstructure.get("order_imbalance") or 0.0)
        liquidity_score = float(microstructure.get("liquidity_score") or 0.0)
        score = liquidity_score
        if spread_bps > 0.0:
            score += max(0.0, 1.0 - min(spread_bps / 100.0, 1.0))
        score += 0.5 * (1.0 - abs(order_imbalance))
        return max(0.0, min(1.0, score / 3.0))

    def _microstructure_bias(self, side: str, microstructure: dict[str, Any]) -> dict[str, float | str]:
        spread_bps = float(microstructure.get("spread_bps") or 0.0)
        order_imbalance = float(microstructure.get("order_imbalance") or 0.0)
        liquidity_score = float(microstructure.get("liquidity_score") or 0.0)
        regime = str(microstructure.get("regime") or "UNKNOWN").upper()

        side_sign = 1.0 if side in {"BUY", "YES", "LONG"} else -1.0
        directional_imbalance = side_sign * order_imbalance

        score_bias = 0.0
        take_profit_bias = 0.0
        stop_loss_bias = 0.0

        if regime == "LIQUID":
            score_bias += 0.15
            take_profit_bias += 0.10
            stop_loss_bias -= 0.05
        elif regime == "THIN":
            score_bias -= 0.20
            take_profit_bias -= 0.10
            stop_loss_bias += 0.15
        elif regime == "IMBALANCED":
            score_bias += 0.10 * directional_imbalance
            take_profit_bias += 0.05 * directional_imbalance
            stop_loss_bias += 0.10 * (1.0 - directional_imbalance)

        if spread_bps > 0.0:
            if spread_bps >= 50.0:
                score_bias -= 0.15
                stop_loss_bias += 0.15
                take_profit_bias -= 0.05
            elif spread_bps >= 20.0:
                score_bias -= 0.05
                stop_loss_bias += 0.05

        if directional_imbalance > 0.25:
            score_bias += 0.10
            take_profit_bias += 0.05
        elif directional_imbalance < -0.25:
            score_bias -= 0.10
            stop_loss_bias += 0.05

        if liquidity_score > 0.75:
            score_bias += 0.05
            take_profit_bias += 0.05
        elif liquidity_score < 0.30:
            score_bias -= 0.10
            stop_loss_bias += 0.10

        return {
            "regime": regime,
            "score_bias": score_bias,
            "take_profit_bias": take_profit_bias,
            "stop_loss_bias": stop_loss_bias,
            "spread_bps": spread_bps,
            "order_imbalance": order_imbalance,
        }

    def _clip(self, value: float) -> float:
        return max(-1.0, min(1.0, float(value)))
