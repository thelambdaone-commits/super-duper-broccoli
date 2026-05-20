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

    assert "Polymarket" in text
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


def test_wallet_deletion_archives_file(tmp_path, monkeypatch) -> None:
    from utils.credential_manager import CredentialManager
    import os

    temp_dir = str(tmp_path / "data")
    os.makedirs(temp_dir, exist_ok=True)
    wallet_path = os.path.join(temp_dir, "polymarket.wallet.enc")
    monkeypatch.setattr("utils.credential_manager.DEFAULT_DATA_DIR", temp_dir)
    monkeypatch.setattr("utils.credential_manager.POLYMARKET_WALLET_PATH", wallet_path)

    mgr = CredentialManager()
    chat_id = 99999
    wtype = "default"
    fake_data = {"address": "0x123", "POLYMARKET_WALLET_ADDRESS": "0x123"}
    mgr.save_user(chat_id, fake_data, wtype)

    path = mgr.get_user_file_path(chat_id, wtype)
    assert os.path.exists(path)
    assert path == wallet_path

    success = mgr.delete_user(chat_id, wtype)
    assert success is True
    assert not os.path.exists(path)

    archive_dir = os.path.join(temp_dir, "archives")
    assert os.path.exists(archive_dir)
    archived_files = os.listdir(archive_dir)
    assert len(archived_files) == 1
    assert archived_files[0].startswith("polymarket_wallet_")
    assert archived_files[0].endswith(".enc")
