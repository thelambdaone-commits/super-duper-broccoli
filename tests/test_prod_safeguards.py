from unittest.mock import patch

import pytest

from main_agentic_clob import PROD_CONFIRMATION_TEXT, require_production_confirmation, resolve_execution_mode
from utils.exceptions import QuantFatal


def test_prod_confirmation_skips_non_prod_modes(monkeypatch):
    monkeypatch.delenv("LOBSTAR_PROD_CONFIRM_SECRET", raising=False)

    require_production_confirmation("PAPER")


def test_prod_confirmation_requires_second_factor(monkeypatch):
    monkeypatch.delenv("LOBSTAR_PROD_CONFIRM_SECRET", raising=False)

    with pytest.raises(QuantFatal, match="LOBSTAR_PROD_CONFIRM_SECRET"):
        require_production_confirmation("PROD")


def test_prod_confirmation_requires_interactive_terminal(monkeypatch):
    monkeypatch.setenv("LOBSTAR_PROD_CONFIRM_SECRET", "expected-secret")
    monkeypatch.delenv("FORCE_PROD", raising=False)

    with patch("main_agentic_clob.sys.stdin.isatty", return_value=False):
        with pytest.raises(QuantFatal, match="interactive terminal"):
            require_production_confirmation("PROD")


def test_prod_confirmation_accepts_noninteractive_force_prod(monkeypatch, caplog):
    monkeypatch.setenv("LOBSTAR_PROD_CONFIRM_SECRET", "expected-secret")
    monkeypatch.setenv("FORCE_PROD", "true")

    with patch("main_agentic_clob.sys.stdin.isatty", return_value=False), caplog.at_level("WARNING"):
        require_production_confirmation("PROD")

    assert "FORCE_PROD=true" in caplog.text


def test_prod_confirmation_accepts_matching_confirmation_and_secret(monkeypatch):
    monkeypatch.setenv("LOBSTAR_PROD_CONFIRM_SECRET", "expected-secret")

    with patch("main_agentic_clob.sys.stdin.isatty", return_value=True), \
        patch("builtins.input", return_value=PROD_CONFIRMATION_TEXT), \
        patch("main_agentic_clob.getpass.getpass", return_value="expected-secret"):
        require_production_confirmation("PROD")


def test_resolve_execution_mode_prefers_cli(monkeypatch):
    monkeypatch.setenv("REAL", "true")
    monkeypatch.setenv("PAPER", "true")

    assert resolve_execution_mode("SHADOW") == "SHADOW"


def test_resolve_execution_mode_prefers_real_when_both_set(monkeypatch, caplog):
    monkeypatch.setenv("REAL", "true")
    monkeypatch.setenv("PAPER", "true")

    with caplog.at_level("INFO"):
        mode = resolve_execution_mode(None)

    assert mode == "PROD"
    assert "Both REAL=true and PAPER=true are set" in caplog.text
    assert "Execution mode resolved from env: PROD" in caplog.text


def test_resolve_execution_mode_defaults_to_paper(monkeypatch, caplog):
    monkeypatch.delenv("REAL", raising=False)
    monkeypatch.delenv("PAPER", raising=False)

    with caplog.at_level("INFO"):
        mode = resolve_execution_mode(None)

    assert mode == "PAPER"
    assert "Execution mode fallback: PAPER" in caplog.text
