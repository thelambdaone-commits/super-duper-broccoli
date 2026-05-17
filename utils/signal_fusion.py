import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Any
import httpx

logger = logging.getLogger("SignalFusion")

MIN_EDGE_THRESHOLD = 0.07
MICROSTRUCTURE_WEIGHT = 0.35
CALIBRATED_WEIGHT = 0.45
SENTIMENT_WEIGHT = 0.20

ERRATIC_VOLATILITY_REGIMES = {"ERRATIC", "HIGH_VOL"}


class SignalSource(Enum):
    MICROSTRUCTURE = "microstructure"
    FREQAI_CALIBRATED = "freqai_calibrated"
    SENTIMENT = "sentiment"
    FUSION = "fusion"


class OrderImbalance(Enum):
    STRONG_BUY = "strong_buy"
    BUY = "buy"
    NEUTRAL = "neutral"
    SELL = "sell"
    STRONG_SELL = "strong_sell"


@dataclass
class MicrostructureSignal:
    order_imbalance: OrderImbalance
    tam_agreement: float
    cancel_velocity: float
    spread: float
    mid_price: float
    volume_ask: float
    volume_bid: float
    timestamp: float = field(default_factory=time.time)

    def to_score(self) -> float:
        oi_scores = {
            OrderImbalance.STRONG_BUY: 1.0,
            OrderImbalance.BUY: 0.6,
            OrderImbalance.NEUTRAL: 0.0,
            OrderImbalance.SELL: -0.6,
            OrderImbalance.STRONG_SELL: -1.0,
        }
        oi_score = oi_scores.get(self.order_imbalance, 0.0)
        tam_score = self.tam_agreement
        cancel_penalty = min(self.cancel_velocity * 0.1, 0.3)
        return (oi_score * 0.5 + tam_score * 0.5) - cancel_penalty


@dataclass
class CalibratedSignal:
    model_prob: float
    market_price: float
    edge: float
    dissimilarity_index: float
    time_decay_factor: float
    time_to_resolution: float
    model_name: str
    brier_score: float = 0.0
    timestamp: float = field(default_factory=time.time)

    def is_ood(self) -> bool:
        return self.dissimilarity_index > 0.8

    def is_valid_edge(self) -> bool:
        return self.edge >= MIN_EDGE_THRESHOLD

    def to_score(self) -> float:
        edge_score = min(self.edge / 0.20, 1.0)
        time_score = self.time_decay_factor
        ood_penalty = 0.5 if self.is_ood() else 0.0
        return (edge_score * 0.6 + time_score * 0.4) - ood_penalty


@dataclass
class SentimentSignal:
    source: str
    raw_message: str
    parsed_ticker: str
    parsed_side: str
    parsed_price: float
    confidence: float
    claude_validation: bool = False
    whale_activity: bool = False
    timestamp: float = field(default_factory=time.time)

    def to_score(self) -> float:
        base = self.confidence
        claude_bonus = 0.2 if self.claude_validation else 0.0
        whale_bonus = 0.15 if self.whale_activity else 0.0
        return min(base + claude_bonus + whale_bonus, 1.0)


@dataclass
class FusedSignal:
    ticker: str
    side: str
    final_score: float
    edge: float
    confidence: float
    microstructure_signal: Optional[MicrostructureSignal] = None
    calibrated_signal: Optional[CalibratedSignal] = None
    sentiment_signal: Optional[SentimentSignal] = None
    is_valid: bool = False
    validation_errors: List[str] = field(default_factory=list)
    regime: str = "UNKNOWN"
    kelly_size: float = 0.0
    created_at: datetime = field(default_factory=datetime.now)
    trade_id: Optional[str] = None


class SignalFusion:
    def __init__(self, polymarket_client=None):
        self.client = polymarket_client
        self._signal_cache: Dict[str, FusedSignal] = {}

    async def get_microstructure_signal(self, ticker: str) -> Optional[MicrostructureSignal]:
        if not self.client:
            return None

        try:
            bids, asks = await self._fetch_orderbook(ticker)
            if not bids or not asks:
                return None

            volume_bid = sum(float(b.get("size", 0)) for b in bids[:3])
            volume_ask = sum(float(a.get("size", 0)) for a in asks[:3])

            total = volume_bid + volume_ask
            if total == 0:
                oi = OrderImbalance.NEUTRAL
            else:
                oi_ratio = (volume_bid - volume_ask) / total
                if oi_ratio > 0.4:
                    oi = OrderImbalance.STRONG_BUY
                elif oi_ratio > 0.15:
                    oi = OrderImbalance.BUY
                elif oi_ratio < -0.4:
                    oi = OrderImbalance.STRONG_SELL
                elif oi_ratio < -0.15:
                    oi = OrderImbalance.SELL
                else:
                    oi = OrderImbalance.NEUTRAL

            mid = (float(bids[0]["price"]) + float(asks[0]["price"])) / 2
            spread = float(asks[0]["price"]) - float(bids[0]["price"])

            tam = await self._calculate_tam_agreement(ticker)

            return MicrostructureSignal(
                order_imbalance=oi,
                tam_agreement=tam,
                cancel_velocity=0.0,
                spread=spread,
                mid_price=mid,
                volume_bid=volume_bid,
                volume_ask=volume_ask,
            )
        except Exception as e:
            logger.error(f"Failed to get microstructure for {ticker}: {e}")
            return None

    async def _fetch_orderbook(self, ticker: str) -> tuple:
        url = f"https://clob.polymarket.com/book?token={ticker}"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    bids = data.get("bids", [])
                    asks = data.get("asks", [])
                    return bids, asks
        except Exception as e:
            logger.error(f"Orderbook fetch error: {e}")
        return [], []

    async def _calculate_tam_agreement(self, ticker: str) -> float:
        return 0.7

    def get_calibrated_signal(
        self,
        ticker: str,
        model_prob: float,
        market_price: float,
        time_to_resolution: float,
        model_name: str = "freqai",
        dissimilarity_index: float = 0.0,
    ) -> CalibratedSignal:
        edge = abs(model_prob - market_price)
        max_time = 86400 * 7
        time_decay = max(0.0, 1.0 - (time_to_resolution / max_time))

        if time_to_resolution < 3600:
            time_decay = min(time_decay * 1.5, 1.0)

        signal = CalibratedSignal(
            model_prob=model_prob,
            market_price=market_price,
            edge=edge,
            dissimilarity_index=dissimilarity_index,
            time_decay_factor=time_decay,
            time_to_resolution=time_to_resolution,
            model_name=model_name,
        )
        return signal

    def parse_sentiment_signal(self, raw_message: str) -> Optional[SentimentSignal]:
        import re
        patterns = [
            r"(BUY|SELL)\s+([A-Z]+)_?[A-Z]*\s*@\s*([0-9.]+)",
            r"(YES|NO)\s+([A-Z]+)\s*@\s*([0-9.]+)",
            r"/trade\s+([A-Z]+)\s+([0-9.]+)\s+(YES|NO)",
        ]

        for pattern in patterns:
            match = re.search(pattern, raw_message.upper())
            if match:
                side = match.group(1)
                ticker = match.group(2)
                price = float(match.group(3))

                return SentimentSignal(
                    source="telegram",
                    raw_message=raw_message,
                    parsed_ticker=ticker,
                    parsed_side=side,
                    parsed_price=price,
                    confidence=0.75,
                )

        return None

    async def fuse_signals(
        self,
        ticker: str,
        regime: str = "UNKNOWN",
        microstructure: Optional[MicrostructureSignal] = None,
        calibrated: Optional[CalibratedSignal] = None,
        sentiment: Optional[SentimentSignal] = None,
    ) -> FusedSignal:
        errors = []
        scores = []
        weights = []
        edge = 0.0

        if microstructure:
            ms_score = microstructure.to_score()
            scores.append(ms_score)
            weights.append(MICROSTRUCTURE_WEIGHT)
        else:
            scores.append(0.0)
            weights.append(0.0)

        if calibrated:
            if calibrated.is_ood():
                errors.append("OOD: Dissimilarity index too high")
            if not calibrated.is_valid_edge():
                errors.append(f"Edge {calibrated.edge:.2%} < {MIN_EDGE_THRESHOLD:.0%}")
            cal_score = calibrated.to_score()
            scores.append(cal_score)
            weights.append(CALIBRATED_WEIGHT)
            edge = calibrated.edge
        else:
            scores.append(0.0)
            weights.append(0.0)

        if sentiment:
            sent_score = sentiment.to_score()
            scores.append(sent_score)
            weights.append(SENTIMENT_WEIGHT)
        else:
            scores.append(0.0)
            weights.append(0.0)

        total_weight = sum(weights)
        if total_weight > 0:
            final_score = sum(s * w for s, w in zip(scores, weights)) / total_weight
        else:
            final_score = 0.0

        is_valid = (
            len(errors) == 0 and
            final_score >= 0.3 and
            regime not in ERRATIC_VOLATILITY_REGIMES
        )

        confidence = min(final_score, 1.0)
        kelly_size = self._calculate_kelly(confidence, edge)

        if regime in ERRATIC_VOLATILITY_REGIMES:
            errors.append(f"Regime {regime} is ERRATIC - blocking trade")

        fused = FusedSignal(
            ticker=ticker,
            side=sentiment.parsed_side if sentiment else "UNKNOWN",
            final_score=final_score,
            edge=edge,
            confidence=confidence,
            microstructure_signal=microstructure,
            calibrated_signal=calibrated,
            sentiment_signal=sentiment,
            is_valid=is_valid,
            validation_errors=errors,
            regime=regime,
            kelly_size=kelly_size,
        )

        self._signal_cache[ticker] = fused
        return fused

    def _calculate_kelly(self, confidence: float, edge: float) -> float:
        if edge <= 0 or confidence <= 0:
            return 0.0

        kelly = (edge * confidence) / 1.0
        kelly = min(kelly, 0.25)
        kelly = max(kelly, 0.01)
        return kelly

    def should_emit_signal(self, fused: FusedSignal) -> bool:
        if not fused.is_valid:
            return False
        if fused.final_score < 0.5:
            return False
        if fused.edge < MIN_EDGE_THRESHOLD:
            return False
        return True

    def format_cognitive_matrix(self, fused: FusedSignal) -> str:
        lines = [
            "🧠 *COGNITIVE MATRIX DECISION*",
            "───────────────────────────────",
        ]

        if fused.microstructure_signal:
            ms = fused.microstructure_signal
            lines.append(f"📊 *MICROSTRUCTURE* (weight: {MICROSTRUCTURE_WEIGHT:.0%})")
            lines.append(f"  • OI: `{ms.order_imbalance.value}`")
            lines.append(f"  • TAM: `{ms.tam_agreement:.2f}`")
            lines.append(f"  • Mid: `${ms.mid_price:.4f}`")

        if fused.calibrated_signal:
            cs = fused.calibrated_signal
            lines.append(f"📈 *FREQAI CALIBRATED* (weight: {CALIBRATED_WEIGHT:.0%})")
            lines.append(f"  • P_real: `{cs.model_prob:.2%}`")
            lines.append(f"  • P_market: `{cs.market_price:.2%}`")
            lines.append(f"  • Edge: `{cs.edge:.2%}`")
            lines.append(f"  • Time-decay: `{cs.time_decay_factor:.2f}`")
            if cs.is_ood():
                lines.append(f"  • ⚠️ OOD: `{cs.dissimilarity_index:.2f}`")

        if fused.sentiment_signal:
            ss = fused.sentiment_signal
            lines.append(f"💬 *SENTIMENT* (weight: {SENTIMENT_WEIGHT:.0%})")
            lines.append(f"  • `{ss.parsed_ticker}` @ `${ss.parsed_price}`")
            lines.append(f"  • Claude validated: `{ss.claude_validation}`")

        lines.append("───────────────────────────────")
        lines.append(f"🎯 *FINAL SCORE:* `{fused.final_score:.2%}`")
        lines.append(f"📐 *EDGE:* `{fused.edge:.2%}`")
        lines.append(f"💵 *KELLY SIZE:* `{fused.kelly_size:.2%}`")
        lines.append(f"🏷️ *REGIME:* `{fused.regime}`")
        lines.append(f"✅ *VALID:* `{fused.is_valid}`")

        if fused.validation_errors:
            lines.append(f"⚠️ *ERRORS:* {', '.join(fused.validation_errors)}")

        return "\n".join(lines)

    def get_latest_fused_signal(self, ticker: str) -> Optional[FusedSignal]:
        return self._signal_cache.get(ticker)

    def clear_cache(self):
        self._signal_cache.clear()