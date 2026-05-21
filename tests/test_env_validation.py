from __future__ import annotations

import pytest

from utils.env_validation import validate_runtime_env
from utils.exceptions import QuantFatal


def test_paper_mode_accepts_minimal_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("CHAT_ID", "123")
    monkeypatch.setenv("ENCRYPTION_KEY", "key")
    validate_runtime_env("PAPER", {"TELEGRAM_BOT_TOKEN": "token"})


def test_shadow_mode_requires_clob_private_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("CHAT_ID", "123")
    monkeypatch.setenv("ENCRYPTION_KEY", "key")
    monkeypatch.setenv("POLYGON_RPC_URL", "https://polygon-rpc.com")
    with pytest.raises(QuantFatal):
        validate_runtime_env("SHADOW", {})


def test_prod_mode_requires_confirmation_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("CHAT_ID", "123")
    monkeypatch.setenv("ENCRYPTION_KEY", "key")
    monkeypatch.setenv("POLYGON_RPC_URL", "https://polygon-rpc.com")
    monkeypatch.setenv("CLOB_PRIVATE_KEY", "0x" + "a" * 64)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(QuantFatal):
        validate_runtime_env("PROD", {"CLOB_PRIVATE_KEY": "0x" + "a" * 64})
