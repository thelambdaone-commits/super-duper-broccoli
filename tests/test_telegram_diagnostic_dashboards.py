from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import json

from interface.command_router import CommandRouter


class _FakeLedger:
    def get_execution_mode(self) -> str:
        return "PROD"

    def get_capital_summary(self) -> dict:
        return {
            "total_capital": 120.0,
            "available_capital": 84.0,
            "allocated_pct": 5.0,
        }

    def get_open_positions(self) -> list[dict]:
        return [
            {
                "position_id": "live-1",
                "ticker": "BTC_5m",
                "side": "BUY",
                "capital_engaged": 12.0,
                "status": "OPEN",
            }
        ]

    def get_paper_positions(self, status: str = "OPEN") -> list[dict]:
        if status == "OPEN":
            return [
                {
                    "position_id": "paper-1",
                    "ticker": "SOL_1h",
                    "side": "BUY",
                    "capital_virtual": 8.0,
                    "status": "OPEN",
                }
            ]
        return []

    def get_closed_positions(self, limit: int = 50, mode: str | None = None) -> list[dict]:
        return [
            {
                "position_id": "closed-1",
                "ticker": "ETH_1h",
                "side": "BUY",
                "pnl": 4.5,
                "is_win": 1,
                "signal_source": "autonomous_strategy:test_alpha",
                "closed_at": "2026-05-24 10:00:00",
            },
            {
                "position_id": "closed-2",
                "ticker": "BTC_15m",
                "side": "SELL",
                "pnl": -2.0,
                "is_win": 0,
                "signal_source": "telegram_btc_launch_15m",
                "closed_at": "2026-05-24 09:30:00",
            },
        ][:limit]

    def get_performance_summary(self, mode: str = "PAPER") -> dict:
        return {
            "total_trades": 2,
            "win_rate": 0.5,
            "total_net_pnl": 2.5,
            "profit_factor": 2.25,
            "avg_win": 4.5,
            "avg_loss": -2.0,
        }

    def get_performance_summary_by_source(self, mode: str | None = None) -> dict:
        return {
            "test_alpha": {"total_pnl": 4.5, "total_trades": 1, "win_rate": 1.0},
            "telegram_btc_launch_15m": {"total_pnl": -2.0, "total_trades": 1, "win_rate": 0.0},
        }


class _FakeMarketReader:
    def __init__(self) -> None:
        self.client = SimpleNamespace(
            get_market=lambda _slug: SimpleNamespace(
                condition_id="cond-1",
                slug="market-slug",
                question="Will the test market resolve YES?",
                yes_price=0.42,
                no_price=0.58,
                spread=0.16,
                volume=25000.0,
                liquidity=8200.0,
                active=True,
                closed=False,
                outcomes=["YES", "NO"],
                end_date="2026-06-01T00:00:00Z",
                fee_rate_bps=200,
            )
        )

    def get_market_snapshot(self, slug: str):
        return SimpleNamespace(
            market_id="cond-1",
            slug=slug,
            question="Will the test market resolve YES?",
            yes_price=0.42,
            no_price=0.58,
            spread=0.16,
            volume=25000.0,
            liquidity=8200.0,
            is_active=True,
            is_closed=False,
            outcomes=["YES", "NO"],
            end_date="2026-06-01T00:00:00Z",
            fee_rate_bps=200,
        )


@pytest.mark.asyncio
async def test_pnl_dashboard_includes_diagnostic_block() -> None:
    wallet_manager = SimpleNamespace(
        recuperer_soldes_on_chain=AsyncMock(return_value={"usdc_direct": 20.0, "usdc_proxy": 40.0})
    )
    listener = SimpleNamespace(
        application=MagicMock(),
        _check_admin_auth=AsyncMock(return_value=True),
        reply_to=AsyncMock(),
        _ledger=_FakeLedger(),
        _resolve_wallet_cockpit_identity=lambda _chat_id: ("default", "0xabc", "0xproxy"),
        _load_pnl_reference_capital=lambda **_kwargs: 100.0,
        _get_wallet_manager=lambda: wallet_manager,
    )
    router = CommandRouter(listener)
    update = MagicMock()
    update.effective_message = SimpleNamespace(chat_id=7413500821)

    await router._cmd_pnl(update, SimpleNamespace(args=[]))

    listener.reply_to.assert_awaited_once()
    text = listener.reply_to.await_args.args[0]
    assert "Polymarket Cockpit" in text
    assert "Bot Diagnostic" in text
    assert "Action recommandée" in text


@pytest.mark.asyncio
async def test_alerts_dashboard_flags_low_win_rate() -> None:
    listener = SimpleNamespace(
        application=MagicMock(),
        _check_admin_auth=AsyncMock(return_value=True),
        reply_to=AsyncMock(),
        _ledger=_FakeLedger(),
        _resolve_wallet_cockpit_identity=lambda _chat_id: ("default", "0xabc", "0xproxy"),
        _load_pnl_reference_capital=lambda **_kwargs: 100.0,
        _get_wallet_manager=lambda: SimpleNamespace(
            recuperer_soldes_on_chain=AsyncMock(return_value={"usdc_direct": 20.0, "usdc_proxy": 40.0})
        ),
    )
    router = CommandRouter(listener)
    update = MagicMock()
    update.effective_message = SimpleNamespace(chat_id=7413500821)

    await router._cmd_alerts(update, SimpleNamespace(args=[]))

    listener.reply_to.assert_awaited_once()
    text = listener.reply_to.await_args.args[0]
    assert "Strategy Alerts" in text
    assert "Action automatique" in text


@pytest.mark.asyncio
async def test_ev_dashboard_uses_market_snapshot() -> None:
    listener = SimpleNamespace(
        application=MagicMock(),
        _check_admin_auth=AsyncMock(return_value=True),
        reply_to=AsyncMock(),
        _ledger=_FakeLedger(),
    )
    router = CommandRouter(listener, market_reader=_FakeMarketReader())
    update = MagicMock()
    update.effective_message = SimpleNamespace(chat_id=7413500821)

    await router._cmd_ev(update, SimpleNamespace(args=["market-slug"]))

    listener.reply_to.assert_awaited_once()
    text = listener.reply_to.await_args.args[0]
    assert "GTO / +EV Engine" in text
    assert "Market Price" in text
    assert "Fair Probability YES" in text
    assert "Net Edge" in text


@pytest.mark.asyncio
async def test_trades_dashboard_lists_recent_closes() -> None:
    listener = SimpleNamespace(
        application=MagicMock(),
        _check_admin_auth=AsyncMock(return_value=True),
        reply_to=AsyncMock(),
        _ledger=_FakeLedger(),
        _resolve_wallet_cockpit_identity=lambda _chat_id: ("default", "0xabc", "0xproxy"),
        _load_pnl_reference_capital=lambda **_kwargs: 100.0,
        _get_wallet_manager=lambda: SimpleNamespace(
            recuperer_soldes_on_chain=AsyncMock(return_value={"usdc_direct": 20.0, "usdc_proxy": 40.0})
        ),
    )
    router = CommandRouter(listener)
    update = MagicMock()
    update.effective_message = SimpleNamespace(chat_id=7413500821)

    await router._cmd_trades(update, SimpleNamespace(args=["2"]))

    listener.reply_to.assert_awaited_once()
    text = listener.reply_to.await_args.args[0]
    assert "Trade Quality" in text
    assert "Recent Closes" in text
    assert "ETH_1h" in text
    assert "BTC_15m" in text


@pytest.mark.asyncio
async def test_sources_dashboard_renders_source_health(tmp_path, monkeypatch) -> None:
    metrics_path = tmp_path / "execution_metrics.jsonl"
    metrics_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "status": "SUCCESS",
                        "signal_source": "autonomous_strategy:test_alpha",
                        "expected_net_profit_usdc": 0.42,
                        "ticker": "ETH_1h",
                    }
                ),
                json.dumps(
                    {
                        "status": "SKIPPED",
                        "signal_source": "telegram_btc_launch_15m",
                        "reason": "REJECT_NO_NET_EDGE:+0.0000",
                        "expected_net_profit_usdc": 0.0,
                        "ticker": "BTC_15m",
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EXECUTION_METRICS_PATH", str(metrics_path))
    listener = SimpleNamespace(
        application=MagicMock(),
        _check_admin_auth=AsyncMock(return_value=True),
        reply_to=AsyncMock(),
        _ledger=_FakeLedger(),
        _resolve_wallet_cockpit_identity=lambda _chat_id: ("default", "0xabc", "0xproxy"),
        _load_pnl_reference_capital=lambda **_kwargs: 100.0,
        _get_wallet_manager=lambda: SimpleNamespace(
            recuperer_soldes_on_chain=AsyncMock(return_value={"usdc_direct": 20.0, "usdc_proxy": 40.0})
        ),
    )
    router = CommandRouter(listener)
    update = MagicMock()
    update.effective_message = SimpleNamespace(chat_id=7413500821)

    await router._cmd_sources(update, SimpleNamespace(args=[]))

    listener.reply_to.assert_awaited_once()
    text = listener.reply_to.await_args.args[0]
    assert "Source Performance" in text
    assert "test_alpha" in text
    assert "Decision Rejects" in text
    assert "REJECT_NO_NET_EDGE" in text
