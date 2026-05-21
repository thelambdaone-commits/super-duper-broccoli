from __future__ import annotations

import importlib

import pytest


def test_mets_telegram_scraper_does_not_read_env_token_at_import(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env-token")
    module = importlib.import_module("scrapers.mets_telegram_scraper")
    importlib.reload(module)

    assert module.TELEGRAM_BOT_TOKEN == ""


@pytest.mark.asyncio
async def test_realtime_connectivity_uses_vault_secrets_for_polygon_rpc(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import verify_realtime_connectivity as vrc

    monkeypatch.setattr(
        vrc.VaultHandler,
        "fetch_quantum_secrets",
        lambda self: {"POLYGON_RPC_URL": "https://example-rpc.invalid"},
    )

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"result": "0x1"}

        text = "ok"

    called = {}

    def fake_post(url, json=None, timeout=None):
        called["url"] = url
        called["json"] = json
        return FakeResponse()

    monkeypatch.setattr(vrc.requests, "post", fake_post)

    result = await vrc.test_rpc_polygon()

    assert called["url"] == "https://example-rpc.invalid"
    assert result["status"] == "SUCCESS"
    assert "Block:" in result["msg"]
