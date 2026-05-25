from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from interface.telegram_listener import TelegramListener


def _build_listener() -> TelegramListener:
    listener = TelegramListener(
        bot_token="token",
        on_signal=lambda signal: None,
        chat_id=None,
        private_chat_ids={123},
        admin_chat_ids={123},
    )
    listener.reply_to = AsyncMock()
    return listener


@pytest.mark.asyncio
async def test_cmd_positions_prefers_live_wallet_positions(monkeypatch: pytest.MonkeyPatch) -> None:
    listener = _build_listener()
    listener._ledger = SimpleNamespace(
        get_execution_mode=lambda: "PROD",
        get_open_positions=lambda: [],
        get_paper_positions=lambda status="OPEN": [],
    )
    monkeypatch.setattr(
        listener,
        "_resolve_wallet_cockpit_identity",
        lambda chat_id: ("default", "0xwallet", "0xproxy"),
    )
    monkeypatch.setattr(
        listener,
        "_fetch_live_polymarket_positions",
        AsyncMock(
            return_value=[
                {
                    "title": "Will BTC close above 100k?",
                    "outcome": "YES",
                    "size": 12,
                    "avgPrice": 0.44,
                    "curPrice": 0.57,
                    "cashPnl": 1.56,
                }
            ]
        ),
    )
    update = SimpleNamespace(effective_message=SimpleNamespace(chat_id=123))

    await listener._cmd_positions(update, None)

    text = listener.reply_to.await_args.args[0]
    assert "Live Polymarket" in text
    assert "Will BTC close above 100k?" in text
    assert "0xproxy" in text
    assert "Écart détecté" in text


@pytest.mark.asyncio
async def test_cmd_positions_reports_both_live_and_ledger(monkeypatch: pytest.MonkeyPatch) -> None:
    listener = _build_listener()
    listener._ledger = SimpleNamespace(
        get_execution_mode=lambda: "PAPER",
        get_open_positions=lambda: [],
        get_paper_positions=lambda status="OPEN": [
            {"ticker": "BTC_5m", "side": "BUY", "size": 3, "entry_price": 0.48}
        ],
    )
    monkeypatch.setattr(
        listener,
        "_resolve_wallet_cockpit_identity",
        lambda chat_id: ("default", "0xwallet", ""),
    )
    monkeypatch.setattr(listener, "_fetch_live_polymarket_positions", AsyncMock(return_value=[]))
    update = SimpleNamespace(effective_message=SimpleNamespace(chat_id=123))

    await listener._cmd_positions(update, None)

    text = listener.reply_to.await_args.args[0]
    assert "Ledger Local (PAPER)" in text
    assert "BTC_5m" in text
    assert "Écart détecté" in text
