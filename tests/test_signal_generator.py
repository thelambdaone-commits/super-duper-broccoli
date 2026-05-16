import pytest
from datetime import datetime
from utils.signal_generator import SignalGenerator, SignalType, TradingSignal


def test_signal_generator_init():
    """Test SignalGenerator initialization."""
    generator = SignalGenerator()
    assert generator.hmm_filter is None
    assert generator.feature_store is None
    assert len(generator._signals_cache) == 0


def test_generate_signal_neutral():
    """Test neutral signal generation."""
    generator = SignalGenerator()
    signal = generator.generate_signal(
        asset="BTC",
        timeframe="15m",
        rsi=50,
        macd_signal=None,
        price_above_ma=None,
    )
    
    assert signal.asset == "BTC"
    assert signal.timeframe == "15m"
    assert signal.signal_type == SignalType.NEUTRAL
    assert signal.rsi == 50


def test_generate_signal_bullish():
    """Test bullish signal generation."""
    generator = SignalGenerator()
    signal = generator.generate_signal(
        asset="SOL",
        timeframe="5m",
        rsi=30,  # Oversold
        macd_signal="bullish",
        price_above_ma=True,
        volume_increasing=True,
    )
    
    assert signal.asset == "SOL"
    assert signal.signal_type in (SignalType.BUY, SignalType.STRONG_BUY)
    assert signal.confidence >= 0.5


def test_generate_signal_bearish():
    """Test bearish signal generation."""
    generator = SignalGenerator()
    signal = generator.generate_signal(
        asset="ETH",
        timeframe="1h",
        rsi=75,  # Overbought
        macd_signal="bearish",
        price_above_ma=False,
        volume_increasing=False,
    )
    
    assert signal.asset == "ETH"
    assert signal.signal_type in (SignalType.SELL, SignalType.STRONG_SELL)
    assert signal.confidence >= 0.5


def test_signal_cache():
    """Test signal caching."""
    generator = SignalGenerator()
    
    signal1 = generator.generate_signal(
        asset="BTC",
        timeframe="15m",
        rsi=40,
    )
    
    cached = generator.get_latest_signals("BTC")
    assert "15m" in cached
    assert cached["15m"] == signal1


def test_signal_history():
    """Test signal history tracking."""
    generator = SignalGenerator()
    
    signal1 = generator.generate_signal("BTC", "5m", rsi=40)
    signal2 = generator.generate_signal("SOL", "15m", rsi=60)
    
    history = generator.get_signal_history()
    assert len(history) >= 2
    assert signal1 in history
    assert signal2 in history


def test_signal_format_markdown():
    """Test markdown formatting."""
    signal = TradingSignal(
        asset="BTC",
        timeframe="15m",
        signal_type=SignalType.BUY,
        confidence=0.85,
        price=50000,
        rsi=35,
        reason="RSI oversold",
    )
    
    markdown = signal.to_markdown()
    assert "📈" in markdown or "BUY" in markdown
    assert "BTC" in markdown
    assert "15" in markdown  # Check for 15 instead of 15m (uppercase)
    assert "85" in markdown  # Confidence will be shown as 85%


def test_signal_format_for_display():
    """Test signal string formatting."""
    signal = TradingSignal(
        asset="ETH",
        timeframe="1h",
        signal_type=SignalType.STRONG_SELL,
        confidence=0.92,
        reason="Multiple bearish indicators",
    )
    
    display = str(signal)
    assert "💥" in display
    assert "ETH" in display
    assert "1h" in display
    assert "0.92" in display


def test_format_signals_report():
    """Test signals report formatting."""
    generator = SignalGenerator()
    
    generator.generate_signal("BTC", "5m", rsi=40)
    generator.generate_signal("BTC", "15m", rsi=50)
    
    report = generator.format_signals_report("BTC")
    assert "📊" in report
    assert "BTC" in report
    assert "5" in report  # Check for 5 (will be 5M in uppercase)
    assert "15" in report


@pytest.mark.asyncio
async def test_generate_signals_for_asset():
    """Test multi-timeframe signal generation."""
    generator = SignalGenerator()
    
    signals = await generator.generate_signals_for_asset(
        "SOL",
        timeframes=["5m", "15m", "1h"],
    )
    
    assert len(signals) == 3
    assert all(s.asset == "SOL" for s in signals)
    assert {s.timeframe for s in signals} == {"5m", "15m", "1h"}


def test_signal_confidence_calculation():
    """Test confidence score calculation."""
    generator = SignalGenerator()
    
    # Strong bullish signal
    strong_bull = generator.generate_signal(
        asset="BTC",
        timeframe="1h",
        rsi=25,  # Oversold
        macd_signal="bullish",
        price_above_ma=True,
        volume_increasing=True,
    )
    
    # Weak signal
    weak = generator.generate_signal(
        asset="ETH",
        timeframe="5m",
        rsi=50,
        macd_signal=None,
        price_above_ma=None,
    )
    
    assert strong_bull.confidence > weak.confidence
