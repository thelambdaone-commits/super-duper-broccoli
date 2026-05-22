from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from utils.exceptions import QuantFatal

BASE_CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"
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


TRADING_PARAMS = {
    "FRICTION_PER_CONTRACT": get_trading_config("friction_per_contract", 0.0, allow_env=False),
    "LEGGING_LIQUIDITY_MIN": get_trading_config("legging_liquidity_min", 10.0, allow_env=False),
    "ARBITRAGE_TRIGGER_THRESHOLD": get_trading_config("arbitrage_trigger_threshold", 0.02, allow_env=False),
    "MIN_EDGE_THRESHOLD": get_trading_config("min_edge_threshold", 0.07, allow_env=False),
    "MAX_REAL_NOTIONAL_USDC": get_trading_config("max_real_notional_usdc", 6.0, allow_env=False),
    "PSI_THRESHOLD": get_trading_config("psi_threshold", 0.2, allow_env=False),
    "KL_THRESHOLD": get_trading_config("kl_threshold", 0.1, allow_env=False),
    "BRIER_THRESHOLD": get_trading_config("brier_threshold", 0.2, allow_env=False),
    "MIN_PAPER_TRADES": get_trading_config("min_paper_trades", 30, allow_env=False),
    "MIN_SHARPE_BACKTEST": get_trading_config("min_sharpe_backtest", 1.5, allow_env=False),
    "MAX_RESOLUTION_WAIT_HOURS": get_trading_config("max_resolution_wait_hours", 24, allow_env=False),
    "MAX_CONCENTRATION_PCT": get_trading_config("max_concentration_pct", 0.30, allow_env=False),
    "MAX_SINGLE_POSITION_PCT": get_trading_config("max_single_position_pct", 0.05, allow_env=False),
    "TARGET_PORTFOLIO_VOL": get_trading_config("target_portfolio_vol", 0.15, allow_env=False),
    "KELLY_FRACTION_DEFAULT": get_trading_config("kelly_fraction_default", 0.25, allow_env=False),
    "SLIPPAGE_GATE_BASE": get_trading_config("slippage_gate_base", 0.012, allow_env=False),
    "SLIPPAGE_GATE_MAX": get_trading_config("slippage_gate_max", 0.05, allow_env=False),
    "GLOBAL_DRAWDOWN_LIMIT": get_trading_config("global_drawdown_limit", -0.10, allow_env=False),
    "FALLBACK_CAPITAL_USDC": get_trading_config("fallback_capital_usdc", 100.0, allow_env=False),
    "BLOCKED_REGIMES": get_trading_config("blocked_regimes", ["ERRATIC_VOLATILITY"], allow_env=False),
    "BANDIT_MULTIPLIER_BASE": get_trading_config("bandit_multiplier_base", 0.75, allow_env=False),
    "BANDIT_MULTIPLIER_RANGE": get_trading_config("bandit_multiplier_range", 0.50, allow_env=False),
    "BANDIT_AGGRESSIVENESS": get_trading_config("bandit_aggressiveness", 3.0, allow_env=False),
    "SELECTION": get_trading_config("selection", {}, allow_env=False),
    "ASSET_BETAS": get_trading_config("asset_betas", {}, allow_env=False),
    "CONFIDENCE_BASE": get_trading_config("confidence_base", 0.5, allow_env=False),
    "CONFIDENCE_STEP": get_trading_config("confidence_step", 0.1, allow_env=False),
    "CONFIDENCE_CAP": get_trading_config("confidence_cap", 0.85, allow_env=False),
    "SHADOW_SIZE_MULTIPLIER": get_trading_config("shadow_size_multiplier", 0.01, allow_env=False),
    "EXECUTION_LOSS_THRESHOLD": get_trading_config("execution_loss_threshold", 0.30, allow_env=False),
    "RESOLUTION_CHECK_INTERVAL": get_trading_config("resolution_check_interval", 30, allow_env=False),
    "AUTONOMOUS": get_trading_config("autonomous", {}, allow_env=False),
}


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
