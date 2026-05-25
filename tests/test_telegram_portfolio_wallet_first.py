from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from interface.telegram_listener import TelegramListener


@pytest.mark.asyncio
async def test_portfolio_prefers_wallet_totals_and_shows_ledger_secondary() -> None:
    listener = TelegramListener(
        bot_token="token",
        on_signal=lambda signal: None,
        chat_id=None,
        private_chat_ids={123},
        admin_chat_ids={123},
    )
    listener.reply_to = AsyncMock()
    listener._ledger = SimpleNamespace(
        get_execution_mode=lambda: "PROD",
        get_capital_summary=lambda: {"total_capital": 85.0, "available_capital": 60.0},
        get_open_positions=lambda: [{"position_id": "live-1"}],
        get_paper_positions=lambda status="OPEN": [],
    )
    listener._risk = SimpleNamespace(net_beta_exposure_pct=7.5)
    listener._resolve_wallet_cockpit_identity = lambda chat_id: ("default", "0xeoa", "0xproxy")
    listener._get_wallet_manager = lambda: SimpleNamespace(
        recuperer_soldes_on_chain=AsyncMock(
            return_value={"usdc_direct": 10.0, "usdc_proxy": 15.0, "eth_balance": 0.01}
        )
    )
    listener._fetch_live_polymarket_positions = AsyncMock(return_value=[{"title": "A"}, {"title": "B"}])
    listener._hmm = None
    update = SimpleNamespace(effective_message=SimpleNamespace(chat_id=123))

    await listener._cmd_portfolio(update, None)

    text = listener.reply_to.await_args.args[0]
    assert "$25.00" in text
    assert "Direct $10.00" in text
    assert "Proxy $15.00" in text
    assert "Live 2" in text
    assert "Ledger 1" in text
    assert "Ledger Total $85.00" in text
