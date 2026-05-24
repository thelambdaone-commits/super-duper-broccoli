from __future__ import annotations

import importlib

import pytest

from utils.env_validation import validate_runtime_env
from utils.exceptions import QuantFatal


def test_validate_runtime_env_accepts_openrouter_from_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("CHAT_ID", "123")
    monkeypatch.setenv("ENCRYPTION_KEY", "key")
    monkeypatch.setenv("CLOB_PRIVATE_KEY", "0x" + "a" * 64)
    monkeypatch.setenv("POLYGON_RPC_URL", "https://polygon-rpc.com")
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_IDS", "123")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    validate_runtime_env(
        "PROD",
        {
            "OPENROUTER_API_KEY": "secret-from-vault",
            "CLOB_PRIVATE_KEY": "0x" + "a" * 64,
        },
    )


@pytest.mark.asyncio
async def test_realtime_connectivity_reads_groq_from_vault(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import verify_realtime_connectivity as vrc

    monkeypatch.setattr(
        vrc.VaultHandler,
        "fetch_quantum_secrets",
        lambda self: {"GROQ_API_KEY": "groq-from-vault"},
    )

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "pong"}}]}

        text = "ok"

    called = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        called["url"] = url
        called["auth"] = headers.get("Authorization")
        return FakeResponse()

    monkeypatch.setattr(vrc.requests, "post", fake_post)

    result = await vrc.test_groq()

    assert called["auth"] == "Bearer groq-from-vault"
    assert result["status"] == "SUCCESS"


@pytest.mark.asyncio
async def test_verify_new_keys_reads_groq_from_vault(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import verify_new_keys as vnk

    monkeypatch.setattr(
        vnk.VaultHandler,
        "fetch_quantum_secrets",
        lambda self: {"GROQ_API_KEY": "groq-from-vault"},
    )

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "pong"}}]}

        text = "ok"

    called = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        called["url"] = url
        called["auth"] = headers.get("Authorization")
        return FakeResponse()

    monkeypatch.setattr(vnk.requests, "post", fake_post)

    result = await vnk.test_groq()

    assert called["auth"] == "Bearer groq-from-vault"
    assert result["status"] == "SUCCESS"
