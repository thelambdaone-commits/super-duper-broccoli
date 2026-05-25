from __future__ import annotations

from services.signal_decision_service import SignalDecisionService


def test_build_microstructure_context_ignores_mismatched_snapshot() -> None:
    service = SignalDecisionService(
        predictive_gate=None,
        risk_engine=None,
        ledger=None,
        snapshot_mgr=None,
    )
    signal = {
        "ticker": "BTC-MKT",
        "token_id": "btc-token",
        "price": 0.51,
        "market_features": {
            "spread_bps": 120.0,
            "order_imbalance": 0.15,
            "bid_depth_3": 150.0,
            "ask_depth_3": 160.0,
            "mid_price": 0.51,
        },
    }
    snapshot = {
        "source": "snapshot_manager",
        "token_id": "eth-token",
        "spread_bps": 900.0,
        "order_imbalance": -0.9,
        "bid_depth_3": 1.0,
        "ask_depth_3": 1.0,
        "mid_price": 0.12,
    }

    context = service.build_microstructure_context(signal, snapshot)

    assert context["source"] == "market_features"
    assert context["spread_bps"] == 120.0
    assert context["mid_price"] == 0.51
    assert context["ticker"] == "BTC-MKT"


def test_build_microstructure_context_uses_matching_snapshot() -> None:
    service = SignalDecisionService(
        predictive_gate=None,
        risk_engine=None,
        ledger=None,
        snapshot_mgr=None,
    )
    signal = {
        "ticker": "BTC-MKT",
        "token_id": "btc-token",
        "price": 0.51,
    }
    snapshot = {
        "source": "snapshot_manager",
        "token_id": "btc-token",
        "spread_bps": 85.0,
        "order_imbalance": 0.18,
        "bid_depth_3": 220.0,
        "ask_depth_3": 180.0,
        "mid_price": 0.52,
    }

    context = service.build_microstructure_context(signal, snapshot)

    assert context["source"] == "snapshot_manager"
    assert context["spread_bps"] == 85.0
    assert context["mid_price"] == 0.52
    assert context["liquidity_regime"] == "LIQUID"
