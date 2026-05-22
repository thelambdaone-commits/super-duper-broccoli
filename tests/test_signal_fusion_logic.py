from __future__ import annotations
import pytest
import time
from utils.signal_fusion import SignalFusionEngine, FusionComponent
from utils.divergence_detector import DivergenceDetector

def test_signal_fusion_consensus():
    engine = SignalFusionEngine(threshold=0.60)

    # 1. Add signals from different experts
    engine.add_signal("btc_15m_fusion", {"ticker": "BTC", "side": "BUY", "confidence": 0.8})
    engine.add_signal("arbitrage_scanner", {"ticker": "BTC", "side": "BUY", "confidence": 0.7})

    # Consensus: (0.40 * 0.8 * 1) + (0.25 * 0.7 * 1) = 0.32 + 0.175 = 0.495
    # Normalize: 0.495 / (0.40 + 0.25) = 0.495 / 0.65 = 0.76
    consensus = engine.compute_consensus("BTC")

    assert consensus is not None
    assert consensus["side"] == "BUY"
    assert consensus["confidence"] >= 0.60
    assert "consensus achieved" in consensus["reason"]

def test_signal_fusion_rejection():
    engine = SignalFusionEngine(threshold=0.80) # Very strict
    engine.add_signal("social_sentiment", {"ticker": "BTC", "side": "BUY", "confidence": 0.5})

    consensus = engine.compute_consensus("BTC")
    assert consensus is None

def test_divergence_detector():
    detector = DivergenceDetector(threshold_bps=10.0)

    detector.update_price("BINANCE", "BTC", 60000.0)
    detector.update_price("COINBASE", "BTC", 59900.0)

    # Divergence: (100 / 59950) * 10000 = ~16.6 bps
    bps = detector.get_divergence("BTC")
    assert bps > 10.0

    alpha = detector.detect_alpha("BTC")
    assert alpha is not None
    assert alpha["direction"] == "UP"
    assert alpha["confidence"] > 0

def test_adaptive_weight_optimization():
    engine = SignalFusionEngine()
    initial_weight = engine.components["social_sentiment"].weight

    # Simulate bad performance for social_sentiment
    perf_data = {
        "social_sentiment": {"total_pnl": -100.0}
    }

    engine.update_weights_from_pnl(perf_data)
    new_weight = engine.components["social_sentiment"].weight

    assert new_weight < initial_weight
    # Check normalization (sum should still be ~1.0)
    assert sum(c.weight for c in engine.components.values()) == pytest.approx(1.0)
