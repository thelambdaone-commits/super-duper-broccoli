import os
from pathlib import Path

from utils.local_dependency_loader import (
    configure_nltk_data_path,
    ensure_local_freqtrade_available,
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
