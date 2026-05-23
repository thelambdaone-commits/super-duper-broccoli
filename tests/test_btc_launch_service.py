from __future__ import annotations

import pandas as pd
import pytest

from core.services.btc_launch_service import BTCDirectionLaunchService


def _btc_frame(rows: int = 240) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=rows, freq="5min")
    base = [
        100000.0
        + ((i % 17) - 8) * 30.0
        + ((i // 9) % 2) * 140.0
        - ((i // 13) % 2) * 110.0
        for i in range(rows)
    ]
    return pd.DataFrame(
        {
            "Open": base,
            "High": [v + 25.0 for v in base],
            "Low": [v - 25.0 for v in base],
            "Close": [v + ((i % 5) - 2) * 3.0 for i, v in enumerate(base)],
            "Volume": [1000.0 + (i % 11) * 17.0 for i in range(rows)],
        },
        index=idx,
    )


def test_btc_launch_service_returns_best_direction(monkeypatch, tmp_path) -> None:
    class _Ticker:
        def history(self, period: str, interval: str):
            return _btc_frame()

    class _YF:
        def Ticker(self, symbol: str):
            assert symbol == "BTC-USD"
            return _Ticker()

    import sys
    sys.modules["yfinance"] = _YF()

    service = BTCDirectionLaunchService(base_model_dir=str(tmp_path))
    result = service.launch("5m", "up")

    assert result.interval == "5m"
    assert result.requested_direction == "up"
    assert result.strongest_direction in {"up", "down"}
    assert 0.0 <= result.prob_up <= 1.0
    assert 0.0 <= result.prob_down <= 1.0
    assert result.best_variant
    assert result.train_samples > 0


def test_btc_launch_service_uses_cache(monkeypatch, tmp_path) -> None:
    calls = {"count": 0}

    class _Ticker:
        def history(self, period: str, interval: str):
            calls["count"] += 1
            return _btc_frame()

    class _YF:
        def Ticker(self, symbol: str):
            assert symbol == "BTC-USD"
            return _Ticker()

    import sys
    sys.modules["yfinance"] = _YF()

    service = BTCDirectionLaunchService(base_model_dir=str(tmp_path), cache_ttl_seconds={"5m": 3600, "15m": 3600})
    first = service.get_or_launch("5m", "up")
    second = service.get_or_launch("5m", "down")

    assert calls["count"] == 3
    assert first.interval == second.interval == "5m"
    assert second.requested_direction == "down"
    assert first.generated_at == second.generated_at
