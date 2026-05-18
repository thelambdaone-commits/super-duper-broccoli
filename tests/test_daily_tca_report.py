from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from scripts.daily_tca_report import DailyTcaReportConfig, DailyTcaReportJob


@dataclass
class FakeBroadcaster:
    diffuser_message_au_canal: AsyncMock


@pytest.mark.asyncio
async def test_daily_tca_report_sends_once_per_day(tmp_path: Path) -> None:
    metrics_path = tmp_path / "execution_metrics.jsonl"
    state_path = tmp_path / "daily_tca_report_state.json"
    metrics_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "asset": "SOL",
                        "requested_qty": 60.0,
                        "filled_qty": 30.0,
                        "execution_price": 0.61,
                        "notional_usd": 18.3,
                        "strategy": "TWAP",
                        "status": "SUCCESS",
                        "slices_filled": 4,
                        "slices_attempted": 4,
                        "realized_participation_rate": 0.25,
                        "avg_market_volume_observed": 120.0,
                        "volume_capped_events": 2,
                        "total_filled_usd": 18.3,
                        "spread_bps": 12.0,
                        "reference_price": 0.58,
                    }
                )
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    broadcaster = FakeBroadcaster(diffuser_message_au_canal=AsyncMock(return_value=True))
    job = DailyTcaReportJob(
        broadcaster=broadcaster,
        config=DailyTcaReportConfig(
            metrics_log_path=str(metrics_path),
            state_path=str(state_path),
            send_hour_utc=8,
            send_minute_utc=0,
            send_window_minutes=5,
        ),
    )
    now = datetime(2026, 5, 17, 8, 1, tzinfo=timezone.utc)

    sent_first = await job.run(now=now)
    sent_second = await job.run(now=now)

    assert sent_first is True
    assert sent_second is False
    assert broadcaster.diffuser_message_au_canal.await_count == 1
    payload = broadcaster.diffuser_message_au_canal.await_args.args[0]
    assert "Daily TCA Report" in payload
    assert "True Completion" in payload
    assert "Avg Slippage" in payload
    assert "SOL" in payload


@pytest.mark.asyncio
async def test_daily_tca_report_skips_outside_window(tmp_path: Path) -> None:
    metrics_path = tmp_path / "execution_metrics.jsonl"
    state_path = tmp_path / "daily_tca_report_state.json"
    metrics_path.write_text(
        json.dumps(
            {
                "asset": "SOL",
                "requested_qty": 10.0,
                "filled_qty": 10.0,
                "execution_price": 0.5,
                "notional_usd": 5.0,
                "strategy": "IMMEDIATE",
                "status": "SUCCESS",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    broadcaster = FakeBroadcaster(diffuser_message_au_canal=AsyncMock(return_value=True))
    job = DailyTcaReportJob(
        broadcaster=broadcaster,
        config=DailyTcaReportConfig(
            metrics_log_path=str(metrics_path),
            state_path=str(state_path),
            send_hour_utc=8,
            send_minute_utc=0,
            send_window_minutes=5,
        ),
    )

    sent = await job.run(now=datetime(2026, 5, 17, 9, 0, tzinfo=timezone.utc))

    assert sent is False
    broadcaster.diffuser_message_au_canal.assert_not_awaited()
