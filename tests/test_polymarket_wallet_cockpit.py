from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from eth_account import Account

from core.wallet_manager import PolymarketWalletManager
from telegram_scraper.telegram_listener import TelegramListener


def test_private_key_import_normalizes_and_derives_address() -> None:
    account = Account.create()
    manager = PolymarketWalletManager(vault_handler=SimpleNamespace())

    address, private_key = manager.importer_via_cle_privee(account.key.hex())

    assert address == account.address
    assert private_key.startswith("0x")


def test_wallet_keyboard_layout_shape() -> None:
    manager = PolymarketWalletManager(vault_handler=SimpleNamespace())

    text, reply_markup = manager.generer_layout_telegram(
        wallet_name="session",
        wallet_address="0x1111111111111111111111111111111111111111",
        soldes={"usdc_balance": 12.3, "eth_balance": 0.4},
        total_connections=1,
    )

    assert "*Polymarket*" in text
    rows = reply_markup.inline_keyboard
    assert [len(row) for row in rows] == [2, 2, 2, 2, 1]
    assert rows[2][1].callback_data == "wallet_show_key"


@pytest.mark.asyncio
async def test_private_wallet_secret_is_deleted_and_stored_in_ram() -> None:
    account = Account.create()
    delete_message = AsyncMock()
    send_message = AsyncMock()
    context = SimpleNamespace(bot=SimpleNamespace(delete_message=delete_message, send_message=send_message))
    message = SimpleNamespace(
        text=account.key.hex(),
        chat_id=123,
        message_id=456,
        chat=SimpleNamespace(type="private"),
    )
    update = SimpleNamespace(message=message, channel_post=None, effective_message=message)
    listener = TelegramListener(
        bot_token="token",
        on_signal=lambda _: None,
        private_chat_ids={123},
    )

    handled = await listener._handle_wallet_secret_import(update, context)

    assert handled is True
    delete_message.assert_awaited_once_with(chat_id=123, message_id=456)
    stored = listener._get_wallet_vault().obtenir_wallet_session(123)
    assert stored["POLYMARKET_WALLET_ADDRESS"] == account.address
    assert stored["CLOB_PRIVATE_KEY"].startswith("0x")
    assert send_message.await_count == 2
