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


def get_config(section: str, key: str, default: Any = None, env_key: str | None = None) -> Any:
    env_name = env_key or key.upper()
    raw_env = os.getenv(env_name)
    if raw_env is not None and raw_env != "":
        return _coerce_like(default, raw_env)

    data = _load_all().get(section, {})
    if key in data:
        return data[key]
    return default


def get_health_config(key: str, default: Any = None, env_key: str | None = None) -> Any:
    return get_config("health", key, default=default, env_key=env_key)


def get_trading_config(key: str, default: Any = None, env_key: str | None = None) -> Any:
    return get_config("trading", key, default=default, env_key=env_key)


TRADING_PARAMS = {
    "FRICTION_PER_CONTRACT": get_trading_config("friction_per_contract", 0.0),
    "MIN_EDGE_THRESHOLD": get_trading_config("min_edge_threshold", 0.07),
    "MAX_REAL_NOTIONAL_USDC": get_trading_config("max_real_notional_usdc", 6.0),
    "PSI_THRESHOLD": get_trading_config("psi_threshold", 0.2),
    "KL_THRESHOLD": get_trading_config("kl_threshold", 0.1),
    "BRIER_THRESHOLD": get_trading_config("brier_threshold", 0.2),
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
