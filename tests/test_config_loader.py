from __future__ import annotations

import json
from pathlib import Path

import pytest

from utils import config_loader
from utils.exceptions import QuantFatal


def test_loads_config_from_json_and_honors_env_override(tmp_path, monkeypatch):
    health = tmp_path / "health.json"
    trading = tmp_path / "trading.json"
    health.write_text(json.dumps({"binance_staleness_seconds": 3.0}), encoding="utf-8")
    trading.write_text(json.dumps({"estimated_trade_fee_bps": 200}), encoding="utf-8")

    monkeypatch.setattr(config_loader, "CONFIG_PATHS", {"health": health, "trading": trading})
    config_loader._load_all.cache_clear()

    assert config_loader.get_health_config("binance_staleness_seconds", 1.0) == 3.0
    monkeypatch.setenv("MAX_BINANCE_STALENESS_SECONDS", "1.5")
    assert config_loader.get_health_config("binance_staleness_seconds", 1.0, env_key="MAX_BINANCE_STALENESS_SECONDS") == 1.5


def test_trading_config_can_ignore_environment_override(tmp_path, monkeypatch):
    health = tmp_path / "health.json"
    trading = tmp_path / "trading.json"
    health.write_text("{}", encoding="utf-8")
    trading.write_text(json.dumps({"twap_default_slices": 7, "model_tickers": ["SOL", "BTC"]}), encoding="utf-8")

    monkeypatch.setattr(config_loader, "CONFIG_PATHS", {"health": health, "trading": trading})
    config_loader._load_all.cache_clear()
    monkeypatch.setenv("TWAP_DEFAULT_SLICES", "99")

    assert config_loader.get_trading_config("twap_default_slices", 5, allow_env=False) == 7
    assert config_loader.TRADING_PARAMS["MIN_EDGE_THRESHOLD"] == 0.07


def test_validate_required_raises_when_missing_file(tmp_path, monkeypatch):
    health = tmp_path / "health.json"
    trading = tmp_path / "trading.json"
    health.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(config_loader, "CONFIG_PATHS", {"health": health, "trading": trading})
    config_loader._load_all.cache_clear()

    with pytest.raises(QuantFatal):
        config_loader.validate_required()
