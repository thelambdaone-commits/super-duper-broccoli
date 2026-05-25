from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from importlib import import_module
from typing import Any

from nautilus_trader.config import ImportableStrategyConfig
from nautilus_trader.config import StrategyFactory as NautilusStrategyFactory
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy

StrategyConfigSpec = Mapping[str, Any]

_PRIMARY_INSTRUMENT_SENTINELS = {None, "__PRIMARY_INSTRUMENT__", "__PRIMARY_INSTRUMENTS__"}


def _is_primary_instrument_sentinel(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value in _PRIMARY_INSTRUMENT_SENTINELS)


def _import_symbol(import_path: str) -> Any:
    module_path, separator, symbol_name = import_path.partition(":")
    if not separator:
        module_path, _, symbol_name = import_path.rpartition(".")
    if not module_path or not symbol_name:
        raise ValueError(f"invalid import path: {import_path!r}")
    return getattr(import_module(module_path), symbol_name)


def _config_field_names(config_path: str) -> set[str]:
    config_cls = _import_symbol(config_path)
    return set(getattr(config_cls, "__struct_fields__", ()))


def _normalized_config(
    *, raw_config: Mapping[str, Any], config_path: str, instrument_id: InstrumentId
) -> dict[str, Any]:
    config = deepcopy(dict(raw_config))
    fields = _config_field_names(config_path)
    supports_instrument_id = "instrument_id" in fields
    supports_instrument_ids = "instrument_ids" in fields

    has_instrument_id = "instrument_id" in config
    has_instrument_ids = "instrument_ids" in config

    if not has_instrument_id and not has_instrument_ids:
        if supports_instrument_id:
            config["instrument_id"] = instrument_id
        elif supports_instrument_ids:
            config["instrument_ids"] = [instrument_id]
        return config

    if _is_primary_instrument_sentinel(config.get("instrument_id")) and has_instrument_id:
        if supports_instrument_id:
            config["instrument_id"] = instrument_id
        elif supports_instrument_ids:
            config.pop("instrument_id", None)
            config["instrument_ids"] = [instrument_id]

    if _is_primary_instrument_sentinel(config.get("instrument_ids")) and has_instrument_ids:
        if supports_instrument_ids:
            config["instrument_ids"] = [instrument_id]
        elif supports_instrument_id:
            config.pop("instrument_ids", None)
            config["instrument_id"] = instrument_id

    if "instrument_id" not in config and "instrument_ids" not in config and supports_instrument_id:
        config["instrument_id"] = instrument_id

    return config


def build_importable_strategy_configs(
    *, strategy_configs: Sequence[StrategyConfigSpec], instrument_id: InstrumentId
) -> list[ImportableStrategyConfig]:
    importable_configs: list[ImportableStrategyConfig] = []
    for spec in strategy_configs:
        strategy_path = str(spec["strategy_path"])
        config_path = str(spec["config_path"])
        raw_config = spec.get("config", {})
        if not isinstance(raw_config, Mapping):
            raise TypeError("strategy config payload must be a mapping")

        importable_configs.append(
            ImportableStrategyConfig(
                strategy_path=strategy_path,
                config_path=config_path,
                config=_normalized_config(
                    raw_config=raw_config,
                    config_path=config_path,
                    instrument_id=instrument_id,
                ),
            )
        )

    return importable_configs


def build_strategies_from_configs(
    *, strategy_configs: Sequence[StrategyConfigSpec], instrument_id: InstrumentId
) -> list[Strategy]:
    return [
        NautilusStrategyFactory.create(importable_config)
        for importable_config in build_importable_strategy_configs(
            strategy_configs=strategy_configs, instrument_id=instrument_id
        )
    ]
