from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from telegram_scraper.telegram_listener import TelegramListener


def _query(callback_data: str):
    message = SimpleNamespace(chat_id=123, reply_text=AsyncMock())
    return SimpleNamespace(
        data=callback_data,
        message=message,
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_crypto_menu_callback_edits_in_place() -> None:
    listener = TelegramListener(
        bot_token="token",
        on_signal=lambda signal: None,
        chat_id=None,
        private_chat_ids={123},
        admin_chat_ids={123},
    )
    listener.command_router = SimpleNamespace(
        render_crypto_menu=AsyncMock(
            return_value=(
                "CRYPTO MENU",
                MagicMock(inline_keyboard=[[SimpleNamespace(callback_data="btc_launch:5m")]]),
            )
        )
    )

    query = _query("crypto_menu")
    update = SimpleNamespace(callback_query=query)
    context = SimpleNamespace()

    await listener._handle_callback(update, context)

    listener.command_router.render_crypto_menu.assert_awaited_once()
    query.answer.assert_awaited_once()
    query.edit_message_text.assert_awaited_once()
