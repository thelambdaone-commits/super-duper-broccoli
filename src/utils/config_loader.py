from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from utils.exceptions import QuantFatal

BASE_CONFIG_DIR = Path(os.getenv("CONFIG_PATH", Path(__file__).resolve().parents[2] / "configs" / "config"))
CONFIG_PATHS = {
    "health": BASE_CONFIG_DIR / "health.json",
    "trading": BASE_CONFIG_DIR / "trading.json",
}


@lru_cache(maxsize=1)
def _load_all() -> dict[str, dict[str, Any]]:
    payload: dict[str, dict[str, Any]] = {}
    for section, path in CONFIG_PATHS.items():
        if not path.exists():
            raise QuantFatal(f"Config file missing: {path}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise QuantFatal(f"Invalid config file {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise QuantFatal(f"Config file must contain an object: {path}")
        payload[section] = data
    return payload


def validate_required() -> None:
    _load_all()


def get_config(
    section: str,
    key: str,
    default: Any = None,
    env_key: str | None = None,
    *,
    allow_env: bool = True,
) -> Any:
    if allow_env:
        env_name = env_key or key.upper()
        raw_env = os.getenv(env_name)
        if raw_env is not None and raw_env != "":
            return _coerce_like(default, raw_env)

    data = _load_all().get(section, {})
    if key in data:
        return data[key]
    return default


def get_health_config(
    key: str,
    default: Any = None,
    env_key: str | None = None,
    *,
    allow_env: bool = True,
) -> Any:
    return get_config("health", key, default=default, env_key=env_key, allow_env=allow_env)


def get_trading_config(
    key: str,
    default: Any = None,
    env_key: str | None = None,
    *,
    allow_env: bool = True,
) -> Any:
    return get_config("trading", key, default=default, env_key=env_key, allow_env=allow_env)


TRADING_DEFAULTS = {
    "FRICTION_PER_CONTRACT": 0.0,
    "ESTIMATED_TRADE_FEE_BPS": 200.0,
    "LEGGING_LIQUIDITY_MIN": 10.0,
    "ARBITRAGE_TRIGGER_THRESHOLD": 0.02,
    "MIN_EDGE_THRESHOLD": 0.07,
    "MIN_EXPECTED_PROFIT_USDC": 0.05,
    "MAX_REAL_NOTIONAL_USDC": 6.0,
    "PSI_THRESHOLD": 0.2,
    "KL_THRESHOLD": 0.1,
    "BRIER_THRESHOLD": 0.2,
    "MIN_PAPER_TRADES": 30,
    "MIN_SHARPE_BACKTEST": 1.5,
    "MAX_RESOLUTION_WAIT_HOURS": 24,
    "MAX_CONCENTRATION_PCT": 0.30,
    "MAX_SINGLE_POSITION_PCT": 0.05,
    "TARGET_PORTFOLIO_VOL": 0.15,
    "KELLY_FRACTION_DEFAULT": 0.25,
    "SLIPPAGE_GATE_BASE": 0.012,
    "SLIPPAGE_GATE_MAX": 0.05,
    "GLOBAL_DRAWDOWN_LIMIT": -0.10,
    "FALLBACK_CAPITAL_USDC": 100.0,
    "BLOCKED_REGIMES": ["ERRATIC_VOLATILITY"],
    "BANDIT_MULTIPLIER_BASE": 0.75,
    "BANDIT_MULTIPLIER_RANGE": 0.50,
    "BANDIT_AGGRESSIVENESS": 3.0,
    "SELECTION": {},
    "ASSET_BETAS": {},
    "CONFIDENCE_BASE": 0.5,
    "CONFIDENCE_STEP": 0.1,
    "CONFIDENCE_CAP": 0.85,
    "SHADOW_SIZE_MULTIPLIER": 0.01,
    "EXECUTION_LOSS_THRESHOLD": 0.30,
    "RESOLUTION_CHECK_INTERVAL": 30,
    "AUTONOMOUS": {},
    "OBJECTIVE": "maximize_polymarket_usdc",
}


def _load_trading_params() -> dict[str, Any]:
    data = _load_all().get("trading", {})
    params: dict[str, Any] = dict(TRADING_DEFAULTS)
    for key, default in TRADING_DEFAULTS.items():
        raw_value = data.get(key.lower(), default)
        if raw_value is None:
            raw_value = default
        if key == "BLOCKED_REGIMES" and (not isinstance(raw_value, list) or not raw_value):
            raw_value = list(default)
        params[key] = raw_value
    return params


TRADING_PARAMS = _load_trading_params()


def _coerce_like(default: Any, raw: str) -> Any:
    if isinstance(default, bool):
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(default, int) and not isinstance(default, bool):
        try:
            return int(float(raw))
        except ValueError:
            return default
    if isinstance(default, float):
        try:
            return float(raw)
        except ValueError:
            return default
    return raw
