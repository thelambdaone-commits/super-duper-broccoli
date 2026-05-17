from unittest.mock import patch

import pytest

from main_agentic_clob import PROD_CONFIRMATION_TEXT, require_production_confirmation
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

    with patch("main_agentic_clob.sys.stdin.isatty", return_value=False):
        with pytest.raises(QuantFatal, match="interactive terminal"):
            require_production_confirmation("PROD")


def test_prod_confirmation_accepts_matching_confirmation_and_secret(monkeypatch):
    monkeypatch.setenv("LOBSTAR_PROD_CONFIRM_SECRET", "expected-secret")

    with patch("main_agentic_clob.sys.stdin.isatty", return_value=True), \
        patch("builtins.input", return_value=PROD_CONFIRMATION_TEXT), \
        patch("main_agentic_clob.getpass.getpass", return_value="expected-secret"):
        require_production_confirmation("PROD")
