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
async def test_btc_paper_callback_records_paper_trade() -> None:
    listener = TelegramListener(
        bot_token="token",
        on_signal=lambda signal: None,
        chat_id=None,
        private_chat_ids={123},
        admin_chat_ids={123},
    )
    listener._btc_launch_service = SimpleNamespace(
        get_or_launch=MagicMock(
            return_value=SimpleNamespace(
                prob_up=0.72,
                prob_down=0.28,
                strongest_probability=0.72,
            )
        )
    )
    listener._ledger = MagicMock()
    listener._ledger.record_paper_order.return_value = {"position_id": "paper-btc-1"}

    query = _query("btc_paper:5m:up")
    update = SimpleNamespace(callback_query=query)
    context = SimpleNamespace()

    await listener._handle_callback(update, context)

    listener._ledger.record_paper_order.assert_called_once()
    query.answer.assert_awaited_once()
    query.message.reply_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_btc_cancel_callback_closes_open_positions() -> None:
    listener = TelegramListener(
        bot_token="token",
        on_signal=lambda signal: None,
        chat_id=None,
        private_chat_ids={123},
        admin_chat_ids={123},
    )
    listener.command_router = SimpleNamespace()
    listener._ledger = MagicMock()
    listener._ledger.get_paper_positions.return_value = [
        {"position_id": "paper-1", "ticker": "BTC_5m"},
        {"position_id": "paper-2", "ticker": "ETH_5m"},
        {"position_id": "paper-3", "ticker": "BTC_5m"},
    ]

    query = _query("btc_cancel:5m")
    update = SimpleNamespace(callback_query=query)
    context = SimpleNamespace()

    await listener._handle_callback(update, context)

    assert listener._ledger.close_paper_position.call_count == 2
    query.answer.assert_awaited_once()
    query.message.reply_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_btc_sl_callback_updates_open_positions() -> None:
    listener = TelegramListener(
        bot_token="token",
        on_signal=lambda signal: None,
        chat_id=None,
        private_chat_ids={123},
        admin_chat_ids={123},
    )
    listener.command_router = SimpleNamespace()
    listener._ledger = MagicMock()
    listener._ledger.get_paper_positions.return_value = [
        {"position_id": "paper-1", "ticker": "BTC_15m"},
        {"position_id": "paper-2", "ticker": "ETH_15m"},
    ]

    query = _query("btc_sl:15m:0.10")
    update = SimpleNamespace(callback_query=query)
    context = SimpleNamespace()

    await listener._handle_callback(update, context)

    listener._ledger.set_position_stop_loss_cents.assert_called_once_with("paper-1", 0.10)
    query.answer.assert_awaited_once()
