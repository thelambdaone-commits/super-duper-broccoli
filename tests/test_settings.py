import pytest

from config.settings import AppSettings


def test_effective_execution_mode_respects_explicit_execution_mode_when_no_flag() -> None:
    settings = AppSettings(execution_mode="SHADOW", paper=False, real=False)

    assert settings.effective_execution_mode() == "SHADOW"


def test_effective_execution_mode_prefers_real_flag() -> None:
    settings = AppSettings(execution_mode="PAPER", paper=False, real=True)

    assert settings.effective_execution_mode() == "PROD"


def test_settings_reject_real_and_paper_conflict() -> None:
    with pytest.raises(ValueError, match="mutually exclusive"):
        AppSettings(real=True, paper=True)
