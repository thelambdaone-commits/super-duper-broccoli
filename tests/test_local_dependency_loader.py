import os
from pathlib import Path

from utils.local_dependency_loader import (
    configure_nltk_data_path,
    ensure_local_freqtrade_available,
    normalize_project_path_env,
    resolve_project_path,
)


def test_configure_nltk_data_path_registers_existing_path(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("NLTK_DATA", "")

    configured = configure_nltk_data_path(tmp_path)

    assert configured == tmp_path
    assert str(tmp_path) in os.environ["NLTK_DATA"]


def test_configure_nltk_data_path_returns_none_for_missing_path(tmp_path: Path) -> None:
    missing = tmp_path / "missing"

    assert configure_nltk_data_path(missing) is None


def test_local_freqtrade_available_from_installed_or_checkout() -> None:
    assert ensure_local_freqtrade_available() is True


def test_resolve_project_path_makes_relative_paths_repo_relative() -> None:
    resolved = resolve_project_path("data")

    assert resolved.name == "data"
    assert resolved.parent.name == "quant-agentic-trading-core"


def test_normalize_project_path_env_rewrites_relative_values(monkeypatch) -> None:
    monkeypatch.setenv("DATA_PATH", "data")
    monkeypatch.setenv("LOG_PATH", "logs")

    normalized = normalize_project_path_env(("DATA_PATH", "LOG_PATH"))

    assert normalized["DATA_PATH"].endswith("/quant-agentic-trading-core/data")
    assert normalized["LOG_PATH"].endswith("/quant-agentic-trading-core/logs")
    assert os.environ["DATA_PATH"] == normalized["DATA_PATH"]
