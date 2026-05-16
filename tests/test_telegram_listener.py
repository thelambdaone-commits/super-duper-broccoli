import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from telegram_scraper.telegram_listener import (
    TELEGRAM_SAFE_MESSAGE_LENGTH,
    TelegramListener,
    _safe_signal_for_log,
    split_telegram_message,
)


@pytest.mark.asyncio
async def test_send_message_returns_false_before_start() -> None:
    listener = TelegramListener(bot_token="token", on_signal=lambda _: None, chat_id=123)

    assert await listener.send_message("hello") is False


@pytest.mark.asyncio
async def test_send_message_uses_configured_chat_id() -> None:
    listener = TelegramListener(bot_token="token", on_signal=lambda _: None, chat_id=123)
    listener.application = SimpleNamespace(
        bot=SimpleNamespace(send_message=AsyncMock())
    )

    assert await listener.send_message("hello") is True
    listener.application.bot.send_message.assert_awaited_once_with(
        chat_id=123,
        text="hello",
    )


@pytest.mark.asyncio
async def test_send_message_accepts_explicit_parse_mode() -> None:
    listener = TelegramListener(bot_token="token", on_signal=lambda _: None, chat_id=123)
    listener.application = SimpleNamespace(
        bot=SimpleNamespace(send_message=AsyncMock())
    )

    assert await listener.send_message("<b>hello</b>", parse_mode="HTML") is True
    listener.application.bot.send_message.assert_awaited_once_with(
        chat_id=123,
        text="<b>hello</b>",
        parse_mode="HTML",
    )


@pytest.mark.asyncio
async def test_send_message_splits_long_text() -> None:
    listener = TelegramListener(bot_token="token", on_signal=lambda _: None, chat_id=123)
    listener.application = SimpleNamespace(
        bot=SimpleNamespace(send_message=AsyncMock())
    )
    text = "a" * (TELEGRAM_SAFE_MESSAGE_LENGTH + 20)

    assert await listener.send_message(text) is True
    assert listener.application.bot.send_message.await_count == 2
    for call in listener.application.bot.send_message.await_args_list:
        assert len(call.kwargs["text"]) <= TELEGRAM_SAFE_MESSAGE_LENGTH


@pytest.mark.asyncio
async def test_reply_to_message_update() -> None:
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(message=message, channel_post=None)
    listener = TelegramListener(bot_token="token", on_signal=lambda _: None)

    assert await listener.reply_to("ok", update) is True
    message.reply_text.assert_awaited_once_with("ok")


@pytest.mark.asyncio
async def test_reply_to_accepts_explicit_parse_mode() -> None:
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(message=message, channel_post=None)
    listener = TelegramListener(bot_token="token", on_signal=lambda _: None)

    assert await listener.reply_to("<b>ok</b>", update, parse_mode="HTML") is True
    message.reply_text.assert_awaited_once_with("<b>ok</b>", parse_mode="HTML")


@pytest.mark.asyncio
async def test_reply_to_channel_post_update() -> None:
    channel_post = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(message=None, channel_post=channel_post)
    listener = TelegramListener(bot_token="token", on_signal=lambda _: None)

    assert await listener.reply_to("ok", update) is True
    channel_post.reply_text.assert_awaited_once_with("ok")


def test_safe_signal_for_log_drops_update_object() -> None:
    signal = {"asset": "SOL", "price": 0.5, "update": object()}

    assert _safe_signal_for_log(signal) == {"asset": "SOL", "price": 0.5}


def test_split_telegram_message_prefers_line_boundaries() -> None:
    chunks = split_telegram_message("line1\nline2\nline3", limit=12)

    assert chunks == ["line1\nline2", "line3"]


@pytest.mark.asyncio
async def test_private_message_signal_is_forwarded_when_authorized() -> None:
    received = []
    message = SimpleNamespace(
        text="BUY SOL @ 0.50",
        message_id=44,
        chat_id=777,
        chat=SimpleNamespace(type="private"),
        reply_text=AsyncMock(),
    )
    update = SimpleNamespace(message=message, channel_post=None)
    listener = TelegramListener(
        bot_token="token",
        on_signal=received.append,
        private_chat_ids={777},
    )

    await listener._handle_private_message(update, None)

    assert len(received) == 1
    assert received[0]["asset"] == "SOL"
    assert received[0]["chat_id"] == 777
    message.reply_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_private_message_replies_help_when_no_signal() -> None:
    message = SimpleNamespace(
        text="hello",
        message_id=45,
        chat_id=777,
        chat=SimpleNamespace(type="private"),
        reply_text=AsyncMock(),
    )
    update = SimpleNamespace(message=message, channel_post=None)
    listener = TelegramListener(
        bot_token="token",
        on_signal=lambda _: None,
        private_chat_ids={777},
    )

    await listener._handle_private_message(update, None)

    message.reply_text.assert_awaited_once()
    assert "/help" in message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_private_message_rejects_unauthorized_chat() -> None:
    message = SimpleNamespace(
        text="BUY SOL @ 0.50",
        message_id=46,
        chat_id=888,
        chat=SimpleNamespace(type="private"),
        reply_text=AsyncMock(),
    )
    update = SimpleNamespace(message=message, channel_post=None)
    listener = TelegramListener(
        bot_token="token",
        on_signal=lambda _: None,
        private_chat_ids={777},
    )

    await listener._handle_private_message(update, None)

    message.reply_text.assert_awaited_once_with("Private chat is not authorized for this bot.")


@pytest.mark.asyncio
async def test_cmd_check_reports_statuses() -> None:
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(message=message, channel_post=None)
    listener = TelegramListener(bot_token="12345678:token", on_signal=lambda _: None)

    # Mock httpx.AsyncClient
    mock_response = SimpleNamespace(status_code=200)
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.aclose = AsyncMock()

    with patch("httpx.AsyncClient", return_value=mock_client):
        with patch.dict(os.environ, {"VAULT_TOKEN": "vtoken", "WS_URL": "ws://test"}):
            await listener._cmd_check(update, None)

    message.reply_text.assert_awaited_once()
    text = message.reply_text.call_args[0][0]
    assert "*API Connectivity Check*" in text
    assert "*Telegram:* token=12345678..." in text
    assert "*Vault:* OK" in text
    assert "*Polymarket CLOB:* OK" in text
    assert "*WebSocket:* CONFIGURED" in text
