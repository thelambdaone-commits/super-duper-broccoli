from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.metrics_exporter import ExecutionMetricsExporter


@pytest.mark.asyncio
async def test_metrics_exporter_writes_jsonl_append_only(tmp_path: Path) -> None:
    output_path = tmp_path / "execution_metrics.jsonl"
    exporter = ExecutionMetricsExporter({"metrics_log_path": str(output_path)})

    signal = {"asset": "SOL", "direction": "BUY", "size_usd": 25.0}
    report = {
        "status": "SUCCESS",
        "strategy": "TWAP",
        "ticker": "SOL",
        "target_price": 0.61,
        "total_filled_usd": 25.0,
        "slices_filled": 3,
        "slices_attempted": 4,
        "realized_participation_rate": 0.25,
        "avg_market_volume_observed": 120.0,
        "volume_capped_events": 2,
        "execution_path": "fragmented_twap",
        "trade_id": "twap-1",
    }

    await exporter.log_execution(signal, report)
    await exporter.log_execution(signal, report)

    lines = output_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    payload = json.loads(lines[0])
    assert payload["asset"] == "SOL"
    assert payload["strategy"] == "TWAP"
    assert payload["realized_participation_rate"] == pytest.approx(0.25)
    assert payload["volume_capped_events"] == 2
    assert payload["total_filled_usd"] == pytest.approx(25.0)
