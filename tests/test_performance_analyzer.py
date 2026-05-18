from __future__ import annotations

import json
from pathlib import Path

import pytest

from utils.performance_analyzer import PerformanceAnalyzer


def test_performance_analyzer_generates_summary(tmp_path: Path) -> None:
    path = tmp_path / "execution_metrics.jsonl"
    rows = [
        {
            "asset": "SOL",
            "direction": "BUY",
            "size_usd": 30.0,
            "strategy": "TWAP",
            "status": "SUCCESS",
            "ticker": "SOL",
            "target_price": 0.61,
            "executed_size_usd": 30.0,
            "slices_filled": 4,
            "slices_attempted": 4,
            "realized_participation_rate": 0.25,
            "avg_market_volume_observed": 120.0,
            "volume_capped_events": 2,
            "total_filled_usd": 30.0,
            "execution_path": "fragmented_twap",
            "trade_id": "twap-1",
            "spread_bps": 60.0,
        },
        {
            "asset": "SOL",
            "direction": "BUY",
            "size_usd": 20.0,
            "strategy": "TWAP",
            "status": "SUCCESS",
            "ticker": "SOL",
            "target_price": 0.63,
            "executed_size_usd": 20.0,
            "slices_filled": 2,
            "slices_attempted": 2,
            "realized_participation_rate": 0.10,
            "avg_market_volume_observed": 200.0,
            "volume_capped_events": 0,
            "total_filled_usd": 20.0,
            "execution_path": "fragmented_twap",
            "trade_id": "twap-2",
            "spread_bps": 40.0,
        },
        {
            "asset": "ETH",
            "direction": "SELL",
            "size_usd": 15.0,
            "strategy": "IMMEDIATE",
            "status": "SUCCESS",
            "ticker": "ETH",
            "target_price": 0.42,
            "executed_size_usd": 15.0,
            "slices_filled": 0,
            "slices_attempted": 0,
            "realized_participation_rate": 0.0,
            "avg_market_volume_observed": 0.0,
            "volume_capped_events": 0,
            "total_filled_usd": 15.0,
            "execution_path": "immediate",
            "trade_id": "imm-1",
            "spread_bps": 18.0,
        },
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    analyzer = PerformanceAnalyzer(metrics_log_path=str(path))
    summary = analyzer.generate_summary()

    assert summary["global"]["total_orders"] == 3
    assert summary["global"]["twap_orders"] == 2
    assert summary["global"]["total_capped_events"] == 2
    assert summary["global"]["volume_capped_ratio"] == pytest.approx(2 / 6)
    assert summary["global"]["completion_rate"] == pytest.approx(6 / 6)
    assert summary["global"]["realized_participation_rate_mean"] == pytest.approx(
        (0.25 * 30.0 + 0.10 * 20.0 + 0.0 * 15.0) / 65.0
    )
    assert summary["global"]["avg_observed_spread_bps"] == pytest.approx((60.0 * 30.0 + 40.0 * 20.0 + 18.0 * 15.0) / 65.0)
    assert summary["assets"]["SOL"]["total_orders"] == 2
    assert summary["assets"]["SOL"]["twap_orders"] == 2
    assert summary["assets"]["SOL"]["volume_capped_ratio"] == pytest.approx(2 / 6)
    assert summary["assets"]["ETH"]["total_orders"] == 1
    assert summary["assets"]["ETH"]["twap_orders"] == 0


def test_performance_analyzer_prefers_reconciliation_fields(tmp_path: Path) -> None:
    path = tmp_path / "execution_metrics.jsonl"
    rows = [
        {
            "asset": "SOL",
            "direction": "BUY",
            "requested_qty": 100.0,
            "filled_qty": 60.0,
            "execution_price": 0.50,
            "notional_usd": 30.0,
            "strategy": "TWAP",
            "status": "SUCCESS",
            "ticker": "SOL",
            "target_price": 0.52,
            "executed_size_usd": 999.0,
            "slices_filled": 3,
            "slices_attempted": 5,
            "realized_participation_rate": 0.10,
            "avg_market_volume_observed": 300.0,
            "volume_capped_events": 1,
            "total_filled_usd": 999.0,
            "execution_path": "fragmented_twap",
            "trade_id": "twap-1",
            "spread_bps": 12.0,
            "reference_price": 0.48,
        }
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    analyzer = PerformanceAnalyzer(metrics_log_path=str(path))
    summary = analyzer.generate_summary()

    assert summary["global"]["total_volume_usd"] == pytest.approx(30.0)
    assert summary["global"]["true_completion_rate"] == pytest.approx(0.60)
    assert summary["global"]["avg_slippage_bps"] == pytest.approx(((0.50 - 0.48) / 0.48) * 10_000.0)
