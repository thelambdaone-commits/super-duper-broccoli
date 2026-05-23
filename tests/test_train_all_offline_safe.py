from __future__ import annotations

from types import SimpleNamespace

import scripts.train_all as train_all


class _Store:
    def get_stats(self):
        return {"features_computed": 1}


class _Pipeline:
    def __init__(self, *args, **kwargs):
        self.model_dir = "user_data/models"

    def register_features(self, *args, **kwargs):
        return None


class _Progress:
    def __init__(self, *args, **kwargs):
        pass

    def close(self):
        return None


def test_train_all_offline_safe_does_not_touch_vault(monkeypatch) -> None:
    monkeypatch.setattr(train_all, "FeatureStore", lambda db_path=None: _Store())
    monkeypatch.setattr(train_all, "TrainingPipeline", _Pipeline)
    monkeypatch.setattr(train_all, "Progress", _Progress)
    monkeypatch.setattr(train_all, "train_configs", lambda *args, **kwargs: [])
    monkeypatch.setattr(train_all, "save_tracking", lambda runs: None)

    touched = {"vault": False}

    class _BrokenVault:
        def __init__(self, *args, **kwargs):
            touched["vault"] = True
            raise AssertionError("Vault should not be touched in offline-safe mode")

    monkeypatch.setitem(train_all.__dict__, "VaultHandler", _BrokenVault)

    train_all.main(
        dry_run=False,
        db_path="/tmp/offline-safe.duckdb",
        allow_synthetic_live=True,
        tickers=["BTC"],
        continuous=False,
        notify_telegram=False,
    )

    assert touched["vault"] is False


def test_train_all_notify_mode_handles_no_successful_runs(monkeypatch) -> None:
    monkeypatch.setattr(train_all, "FeatureStore", lambda db_path=None: _Store())
    monkeypatch.setattr(train_all, "TrainingPipeline", _Pipeline)
    monkeypatch.setattr(train_all, "Progress", _Progress)
    monkeypatch.setattr(train_all, "train_configs", lambda *args, **kwargs: [])
    monkeypatch.setattr(train_all, "save_tracking", lambda runs: None)

    class _Vault:
        def fetch_quantum_secrets(self):
            return {"TELEGRAM_BOT_TOKEN": "token"}

    class _Response:
        status_code = 200

    captured = {}

    monkeypatch.setenv("CHAT_ID", "123")
    monkeypatch.setitem(train_all.__dict__, "httpx", SimpleNamespace(post=lambda url, json, timeout: captured.update({"url": url, "payload": json}) or _Response()))

    import sys
    import types

    sys.modules["utils.vault_handler"] = types.SimpleNamespace(VaultHandler=_Vault)

    train_all.main(
        dry_run=False,
        db_path="/tmp/offline-safe.duckdb",
        allow_synthetic_live=True,
        tickers=["BTC"],
        continuous=False,
        notify_telegram=True,
    )

    assert "Best Model: `N/A`" in captured["payload"]["text"]
