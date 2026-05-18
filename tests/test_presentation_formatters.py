from __future__ import annotations

from utils.presentation_formatters import (
    format_cognitive_decision_notification,
    format_execution_notification,
)


def test_cognitive_decision_notification_handles_microstructure_fields() -> None:
    message = format_cognitive_decision_notification(
        {
            "action": "EXECUTE",
            "reason": "synthetic-e2e",
            "microstructure_regime": "LIQUID",
            "observed_liquidity_score": 0.88,
            "take_profit_bias": 0.12,
            "stop_loss_bias": -0.04,
            "spread_bps": 18.0,
            "order_imbalance": 0.22,
        },
        ticker="SOL",
    )

    assert "Décision Lobstar Cognitive Brain" in message
    assert "Régime CLOB" in message
    assert "Score Liquidité" in message
    assert "TP Bias" in message
    assert "SL Bias" in message


def test_execution_notification_handles_twap_report() -> None:
    message = format_execution_notification(
        {"ticker": "SOL", "side": "BUY"},
        {
            "strategy": "TWAP",
            "ticker": "SOL",
            "side": "BUY",
            "requested_qty": 60.0,
            "filled_qty": 30.0,
            "execution_price": 0.61,
            "notional_usd": 18.3,
            "slices_attempted": 4,
            "slices_filled": 4,
            "total_filled_usd": 30.0,
            "avg_market_volume_observed": 120.0,
            "realized_participation_rate": 0.25,
            "volume_capped_events": 2,
            "true_completion_rate": 0.5,
            "execution_preference": "PASSIVE_ONLY",
        },
        execution_mode="PAPER",
        success=True,
    )

    assert "Trade Executed" in message
    assert "TWAP" in message
    assert "PR Réalisé" in message
    assert "Requested" in message
    assert "Filled" in message
    assert "Notional" in message
    assert "Completion Réelle" in message
    assert "PASSIVE_ONLY" in message
