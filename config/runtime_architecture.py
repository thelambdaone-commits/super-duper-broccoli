from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class StorageArchitecture:
    operational_db: str = "sqlite"
    hot_counter_store: str = "redis"
    analytical_store: str = "duckdb"
    archival_tick_store: str = "parquet"


@dataclass(frozen=True)
class ModelArchitecture:
    pnl_prediction_stack: tuple[str, ...] = ("xgboost", "lightgbm", "random_forest")
    optional_sequence_models: tuple[str, ...] = ("lstm", "small_transformer")
    optional_offline_rl: tuple[str, ...] = ("cql",)
    runtime_model_family: str = "hybrid_tabular_first"


@dataclass(frozen=True)
class SafetyArchitecture:
    simulation_only_learning: bool = True
    forbid_private_keys_in_learning: bool = True
    require_position_caps: bool = True
    require_circuit_breakers: bool = True
    allow_telegram_notifications_from_training: bool = False


@dataclass(frozen=True)
class RuntimeArchitecture:
    storage: StorageArchitecture = field(default_factory=StorageArchitecture)
    models: ModelArchitecture = field(default_factory=ModelArchitecture)
    safety: SafetyArchitecture = field(default_factory=SafetyArchitecture)


DEFAULT_RUNTIME_ARCHITECTURE = RuntimeArchitecture()
