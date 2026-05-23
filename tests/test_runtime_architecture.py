from __future__ import annotations

from config.runtime_architecture import DEFAULT_RUNTIME_ARCHITECTURE


def test_runtime_architecture_defaults_match_policy() -> None:
    assert DEFAULT_RUNTIME_ARCHITECTURE.storage.operational_db == "sqlite"
    assert DEFAULT_RUNTIME_ARCHITECTURE.storage.hot_counter_store == "redis"
    assert DEFAULT_RUNTIME_ARCHITECTURE.storage.archival_tick_store == "parquet"
    assert DEFAULT_RUNTIME_ARCHITECTURE.models.pnl_prediction_stack[:2] == ("xgboost", "lightgbm")
    assert DEFAULT_RUNTIME_ARCHITECTURE.safety.simulation_only_learning is True
    assert DEFAULT_RUNTIME_ARCHITECTURE.safety.forbid_private_keys_in_learning is True
    assert DEFAULT_RUNTIME_ARCHITECTURE.safety.allow_telegram_notifications_from_training is False
