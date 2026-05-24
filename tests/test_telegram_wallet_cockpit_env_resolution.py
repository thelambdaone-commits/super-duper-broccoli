from __future__ import annotations

from types import SimpleNamespace

from eth_account import Account

from telegram_scraper.telegram_listener import TelegramListener


def test_wallet_cockpit_prefers_env_private_key_without_generating_wallet(monkeypatch) -> None:
    private_key = "0x" + "1" * 64
    expected_address = Account.from_key(private_key).address

    monkeypatch.delenv("POLYMARKET_WALLET_ADDRESS", raising=False)
    monkeypatch.setenv("CLOB_PRIVATE_KEY", private_key)

    listener = TelegramListener(
        bot_token="token",
        on_signal=lambda signal: None,
        chat_id=None,
        private_chat_ids={123},
        admin_chat_ids={123},
    )
    listener._get_wallet_vault = lambda: SimpleNamespace(obtenir_wallet_session=lambda _chat_id: None)

    wallet_name, wallet_address, proxy_address = listener._resolve_wallet_cockpit_identity(123)

    assert wallet_name == "default"
    assert wallet_address == expected_address
    assert proxy_address == ""
