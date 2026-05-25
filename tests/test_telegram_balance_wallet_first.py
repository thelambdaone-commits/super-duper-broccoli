from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from interface.telegram_listener import TelegramListener


@pytest.mark.asyncio
async def test_balance_prefers_wallet_balances_and_keeps_ledger_as_secondary(monkeypatch: pytest.MonkeyPatch) -> None:
    listener = TelegramListener(
        bot_token="token",
        on_signal=lambda signal: None,
        chat_id=None,
        private_chat_ids={123},
        admin_chat_ids={123},
    )
    listener.reply_to = AsyncMock()
    listener._ledger = SimpleNamespace(
        get_capital_summary=lambda: {
            "total_capital": 90.0,
            "available_capital": 70.0,
        }
    )
    listener._resolve_wallet_cockpit_identity = lambda chat_id: (
        "default",
        "0xeoa",
        "0xproxy",
    )
    listener._get_wallet_manager = lambda: SimpleNamespace(
        recuperer_soldes_on_chain=AsyncMock(
            return_value={
                "usdc_direct": 12.5,
                "usdc_proxy": 37.5,
                "eth_balance": 0.042,
            }
        )
    )

    class _Container:
        async def sync_real_capital(self) -> None:
            return None

    monkeypatch.setattr(
        "core.container.ServiceContainer.get_instance",
        lambda: _Container(),
    )

    update = SimpleNamespace(effective_message=SimpleNamespace(chat_id=123), callback_query=None)

    await listener._cmd_balance(update, None)

    text = listener.reply_to.await_args.args[0]
    assert "On-chain Total: <b>50.00 USD</b>" in text
    assert "USDC Direct: <b>12.50 USD</b>" in text
    assert "Polymarket pUSD: <b>37.50 USD</b>" in text
    assert "Ledger Total: <code>90.00 USD</code>" in text
