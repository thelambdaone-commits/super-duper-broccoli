from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from telegram_scraper.command_router import CommandRouter


@pytest.mark.asyncio
async def test_crypto_menu_horizon_buttons_cover_each_asset() -> None:
    listener = SimpleNamespace(
        application=MagicMock(),
        reply_to=AsyncMock(),
        _check_auth=AsyncMock(return_value=True),
    )
    router = CommandRouter(listener)
    update = MagicMock()
    context = SimpleNamespace(args=[])

    await router._cmd_crypto(update, context)

    _, kwargs = listener.reply_to.await_args
    markup = kwargs["reply_markup"]
    callback_data = [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
    ]

    assert "crypto_horizon:btc:5" in callback_data
    assert "crypto_horizon:eth:1h" in callback_data
    assert "crypto_horizon:sol:4h" in callback_data
    assert "crypto_horizon:xrp:1d" in callback_data
    assert "crypto_horizon:bnb:15" in callback_data
