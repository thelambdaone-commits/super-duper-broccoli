import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.factories import build_telegram_listener
from interface.telegram_listener import TelegramListener
from utils.access_control import AccessControlManager


ADMIN_CHAT_ID = int(os.environ.get("TELEGRAM_ADMIN_CHAT_IDS", "123456789").split(",")[0])
CHANNEL_CHAT_ID = int(os.environ.get("CHAT_ID", "-987654321"))


def _update(chat_id: int, user_id: int | None = None, chat_type: str = "private"):
    user = SimpleNamespace(id=user_id) if user_id is not None else None
    chat = SimpleNamespace(id=chat_id, type=chat_type)
    message = SimpleNamespace(chat_id=chat_id, chat=chat)
    return SimpleNamespace(
        effective_message=message,
        message=message,
        channel_post=None,
        effective_user=user,
    )


def test_listener_uses_admin_private_chat_when_chat_id_is_channel(monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_PRIVATE_CHAT_IDS", raising=False)
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_IDS", str(ADMIN_CHAT_ID))

    listener = build_telegram_listener(
        secrets={"TELEGRAM_BOT_TOKEN": "token"},
        on_signal=lambda signal: None,
        chat_id=CHANNEL_CHAT_ID,
        access_control=AccessControlManager([ADMIN_CHAT_ID]),
    )

    assert listener.chat_id == ADMIN_CHAT_ID
    assert listener.private_chat_ids == {ADMIN_CHAT_ID}
    assert listener.admin_chat_ids == {ADMIN_CHAT_ID}


@pytest.mark.asyncio
async def test_admin_private_chat_is_authorized_when_chat_id_is_channel() -> None:
    listener = TelegramListener(
        bot_token="token",
        on_signal=lambda signal: None,
        chat_id=None,
        private_chat_ids={ADMIN_CHAT_ID},
        admin_chat_ids={ADMIN_CHAT_ID},
        access_control=AccessControlManager([ADMIN_CHAT_ID]),
    )
    listener.reply_to = AsyncMock(return_value=True)

    assert await listener._check_auth(_update(ADMIN_CHAT_ID, ADMIN_CHAT_ID)) is True
    listener.reply_to.assert_not_called()


@pytest.mark.asyncio
async def test_channel_chat_is_not_authorized_for_interactive_commands() -> None:
    listener = TelegramListener(
        bot_token="token",
        on_signal=lambda signal: None,
        chat_id=None,
        private_chat_ids={ADMIN_CHAT_ID},
        admin_chat_ids={ADMIN_CHAT_ID},
        access_control=AccessControlManager([ADMIN_CHAT_ID]),
    )
    listener.reply_to = AsyncMock(return_value=True)

    assert await listener._check_auth(_update(CHANNEL_CHAT_ID, None, chat_type="channel")) is False
    listener.reply_to.assert_awaited_once()


@pytest.mark.asyncio
async def test_listener_without_any_acl_rejects_interactive_commands() -> None:
    listener = TelegramListener(
        bot_token="token",
        on_signal=lambda signal: None,
        chat_id=None,
        private_chat_ids=None,
        admin_chat_ids=None,
        access_control=None,
    )
    listener.reply_to = AsyncMock(return_value=True)

    assert await listener._check_auth(_update(12345, 12345, chat_type="private")) is False
    listener.reply_to.assert_awaited_once()


@pytest.mark.asyncio
async def test_channel_command_reply_is_redirected_to_admin_private_chat() -> None:
    listener = TelegramListener(
        bot_token="token",
        on_signal=lambda signal: None,
        chat_id=ADMIN_CHAT_ID,
        private_chat_ids={ADMIN_CHAT_ID},
        admin_chat_ids={ADMIN_CHAT_ID},
        access_control=AccessControlManager([ADMIN_CHAT_ID]),
    )
    bot = SimpleNamespace(send_message=AsyncMock())
    listener.application = SimpleNamespace(bot=bot)

    channel_update = _update(CHANNEL_CHAT_ID, ADMIN_CHAT_ID, chat_type="channel")
    channel_update.effective_message.text = "/status"
    channel_update.message.reply_text = AsyncMock()

    sent = await listener.reply_to("STATUS", channel_update)

    assert sent is True
    channel_update.message.reply_text.assert_not_called()
    bot.send_message.assert_awaited_once_with(
        chat_id=ADMIN_CHAT_ID,
        text="STATUS",
        parse_mode="HTML",
    )
