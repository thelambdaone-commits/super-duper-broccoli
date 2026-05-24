from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from interface.telegram_listener import TelegramListener


@pytest.mark.asyncio
async def test_start_uses_resolved_wallet_without_generation() -> None:
    listener = TelegramListener(
        bot_token="token",
        on_signal=lambda signal: None,
        chat_id=None,
        private_chat_ids={123},
        admin_chat_ids={123},
    )
    listener._get_mode = lambda: "PAPER"
    listener._fmt_uptime = lambda: "1m"
    listener.reply_to = AsyncMock()
    listener._resolve_wallet_cockpit_identity = lambda chat_id: (
        "default",
        "0xdc5585FC1cEDf10EECedB9D71f02f13b34cf614E",
        "0xa005088ba69014581d6460db325627600887590b",
    )

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=123),
        callback_query=None,
        effective_message=SimpleNamespace(reply_text=AsyncMock()),
        message=SimpleNamespace(reply_text=AsyncMock()),
    )

    await listener._cmd_start(update, None)

    sent_text = listener.reply_to.await_args.args[0]
    assert "0xdc5585FC1cEDf10EECedB9D71f02f13b34cf614E" in sent_text
    assert "💬 <b>Active Wallet</b> : <code>DEFAULT</code>" in sent_text
    assert "UNKNOWN" not in sent_text

