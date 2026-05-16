import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Callable

logger = logging.getLogger("SignalGenerator")


class SignalType(Enum):
    """Trading signal types."""
    STRONG_BUY = "🚀"
    BUY = "📈"
    NEUTRAL = "⏸️"
    SELL = "📉"
    STRONG_SELL = "💥"
    WAIT = "⏳"


class Timeframe(Enum):
    """Supported timeframes."""
    M5 = 300  # 5 minutes
    M15 = 900  # 15 minutes
    M30 = 1800  # 30 minutes
    H1 = 3600  # 1 hour
    H4 = 14400  # 4 hours
    D1 = 86400  # 1 day


@dataclass
class TradingSignal:
    """A trading signal for a specific asset and timeframe."""
    asset: str  # "BTC", "SOL", "ETH", etc.
    timeframe: str  # "5m", "15m", "1h", etc.
    signal_type: SignalType
    confidence: float  # 0.0-1.0
    price: Optional[float] = None
    rsi: Optional[float] = None
    macd: Optional[str] = None  # "bullish" or "bearish"
    moving_avg_signal: Optional[str] = None  # "above" or "below"
    volume_signal: Optional[str] = None  # "increasing" or "decreasing"
    generated_at: datetime = field(default_factory=datetime.utcnow)
    reason: Optional[str] = None

    def __str__(self) -> str:
        """Format signal for display."""
        return (
            f"{self.signal_type.value} **{self.asset} {self.timeframe}** "
            f"| Conf: {self.confidence:.2f} | {self.reason or 'N/A'}"
        )

    def to_markdown(self) -> str:
        """Convert to markdown message."""
        lines = [
            f"{self.signal_type.value} **{self.asset.upper()} {self.timeframe.upper()}**",
            f"• Signal: `{self.signal_type.name}`",
            f"• Confidence: `{self.confidence:.2%}`",
        ]
        
        if self.price:
            lines.append(f"• Price: `${self.price:.2f}`")
        if self.rsi is not None:
            lines.append(f"• RSI: `{self.rsi:.1f}`")
        if self.macd:
            lines.append(f"• MACD: `{self.macd}`")
        if self.moving_avg_signal:
            lines.append(f"• MA: `{self.moving_avg_signal}`")
        if self.volume_signal:
            lines.append(f"• Volume: `{self.volume_signal}`")
        if self.reason:
            lines.append(f"• Reason: {self.reason}")
        
        return "\n".join(lines)


class SignalGenerator:
    """Generates trading signals for multiple assets and timeframes."""

    def __init__(
        self,
        hmm_filter=None,
        feature_store=None,
        market_scanner=None,
    ):
        """
        Initialize signal generator with optional components.
        
        Args:
            hmm_filter: HMM regime filter for regime detection
            feature_store: Feature store for technical indicators
            market_scanner: Market scanner for market data
        """
        self.hmm_filter = hmm_filter
        self.feature_store = feature_store
        self.market_scanner = market_scanner
        
        self._signals_cache: dict[str, dict[str, TradingSignal]] = {}
        self._last_signal_time: dict[str, datetime] = {}
        self._signal_history: list[TradingSignal] = []

    def _get_rsi(self, asset: str, period: int = 14) -> Optional[float]:
        """Get RSI from feature store or calculate."""
        try:
            if self.feature_store:
                # Try to get from feature store
                features = self.feature_store.get_features(asset)
                if features and "rsi" in features:
                    return float(features["rsi"])
            # Otherwise return None (would need price history to calculate)
            return None
        except Exception as e:
            logger.debug(f"Failed to get RSI for {asset}: {e}")
            return None

    def _check_hmm_regime(self, asset: str) -> tuple[bool, str]:
        """Check HMM regime for asset."""
        try:
            if not self.hmm_filter:
                return True, "No HMM filter"
            
            allowed, regime = self.hmm_filter.is_trading_allowed(asset)
            return allowed, regime
        except Exception as e:
            logger.debug(f"Failed to check HMM regime: {e}")
            return True, "Unknown"

    def generate_signal(
        self,
        asset: str,
        timeframe: str,
        current_price: Optional[float] = None,
        rsi: Optional[float] = None,
        macd_signal: Optional[str] = None,
        volume_increasing: Optional[bool] = None,
        price_above_ma: Optional[bool] = None,
    ) -> TradingSignal:
        """
        Generate a trading signal based on provided indicators.
        
        Args:
            asset: Asset symbol (e.g., "BTC", "SOL", "ETH")
            timeframe: Timeframe (e.g., "5m", "15m", "1h")
            current_price: Current asset price
            rsi: RSI value (0-100)
            macd_signal: "bullish" or "bearish"
            volume_increasing: Whether volume is increasing
            price_above_ma: Whether price is above moving average
        
        Returns:
            TradingSignal with confidence and reasoning
        """
        signal_type = SignalType.NEUTRAL
        confidence = 0.5
        reasons = []

        # Check HMM regime
        allowed, regime = self._check_hmm_regime(asset)
        if not allowed:
            signal_type = SignalType.WAIT
            confidence = 0.0
            reasons.append(f"Trading not allowed ({regime})")
        else:
            # Count bullish indicators
            bullish_count = 0
            bearish_count = 0

            if rsi is not None:
                if rsi < 30:
                    bullish_count += 1
                    reasons.append("RSI oversold")
                elif rsi > 70:
                    bearish_count += 1
                    reasons.append("RSI overbought")

            if macd_signal == "bullish":
                bullish_count += 1
                reasons.append("MACD bullish")
            elif macd_signal == "bearish":
                bearish_count += 1
                reasons.append("MACD bearish")

            if price_above_ma is True:
                bullish_count += 1
                reasons.append("Price above MA")
            elif price_above_ma is False:
                bearish_count += 1
                reasons.append("Price below MA")

            if volume_increasing is True:
                bullish_count += 1
                reasons.append("Volume increasing")

            # Determine signal and confidence
            total_indicators = bullish_count + bearish_count
            if total_indicators == 0:
                signal_type = SignalType.NEUTRAL
                confidence = 0.5
                reasons.append("Insufficient data")
            else:
                bullish_ratio = bullish_count / total_indicators
                confidence = abs(bullish_ratio - bearish_count / total_indicators)

                if bullish_ratio > 0.75:
                    signal_type = SignalType.STRONG_BUY if confidence > 0.75 else SignalType.BUY
                elif bullish_ratio > 0.5:
                    signal_type = SignalType.BUY
                elif bearish_count / total_indicators > 0.75:
                    signal_type = SignalType.STRONG_SELL if confidence > 0.75 else SignalType.SELL
                elif bearish_count / total_indicators > 0.5:
                    signal_type = SignalType.SELL
                else:
                    signal_type = SignalType.NEUTRAL
                    confidence = 0.5

        signal = TradingSignal(
            asset=asset.upper(),
            timeframe=timeframe,
            signal_type=signal_type,
            confidence=min(confidence, 1.0),
            price=current_price,
            rsi=rsi,
            macd=macd_signal,
            moving_avg_signal="above" if price_above_ma else ("below" if price_above_ma is False else None),
            reason=" | ".join(reasons) if reasons else None,
        )

        # Cache the signal
        if asset not in self._signals_cache:
            self._signals_cache[asset] = {}
        self._signals_cache[asset][timeframe] = signal

        # Add to history
        self._signal_history.append(signal)
        self._last_signal_time[f"{asset}_{timeframe}"] = datetime.utcnow()

        logger.info(f"Generated signal: {signal}")
        return signal

    async def generate_signals_for_asset(
        self, asset: str, timeframes: list[str] = None, fetch_fn: Optional[Callable] = None
    ) -> list[TradingSignal]:
        """
        Generate signals for an asset across multiple timeframes.
        
        Args:
            asset: Asset symbol
            timeframes: List of timeframes (default: ["5m", "15m", "1h"])
            fetch_fn: Optional async function to fetch price data
        
        Returns:
            List of TradingSignal for each timeframe
        """
        if timeframes is None:
            timeframes = ["5m", "15m", "1h"]

        signals = []
        for tf in timeframes:
            try:
                # For now, generate with placeholder data
                # In production, would fetch actual price data and indicators
                signal = self.generate_signal(
                    asset=asset,
                    timeframe=tf,
                    rsi=None,
                    macd_signal=None,
                    price_above_ma=None,
                )
                signals.append(signal)
            except Exception as e:
                logger.error(f"Failed to generate signal for {asset} {tf}: {e}")

        return signals

    def get_latest_signals(self, asset: str = None) -> dict[str, TradingSignal]:
        """Get latest signals for asset or all assets."""
        if asset:
            return self._signals_cache.get(asset.upper(), {})
        return self._signals_cache

    def format_signals_report(self, asset: str = None) -> str:
        """Format signals as a report."""
        signals = self.get_latest_signals(asset)
        
        if not signals:
            return "No signals generated yet"
        
        lines = [f"📊 **Trading Signals Report**\n"]
        for tf, signal in signals.items():
            lines.append(signal.to_markdown())
            lines.append("")  # Blank line between signals

        return "\n".join(lines)

    def start_periodic_signals(
        self,
        assets: list[str],
        interval_seconds: int = 300,  # 5 minutes
    ):
        """
        Start periodic signal generation.
        
        Args:
            assets: List of assets to generate signals for
            interval_seconds: Interval between signal generations
        
        Returns:
            asyncio Task that runs the signal generator
        """
        async def _periodic_signal_loop():
            while True:
                try:
                    for asset in assets:
                        await self.generate_signals_for_asset(asset)
                    await asyncio.sleep(interval_seconds)
                except Exception as e:
                    logger.error(f"Error in periodic signal loop: {e}")
                    await asyncio.sleep(interval_seconds)

        return asyncio.create_task(_periodic_signal_loop())

    def get_signal_history(self, limit: int = 50) -> list[TradingSignal]:
        """Get recent signal history."""
        return self._signal_history[-limit:]
