from __future__ import annotations

from types import SimpleNamespace

import pytest

from interface.telegram_listener import TelegramListener
from unittest.mock import AsyncMock


class StubRunner:
    def get_job_stats(self) -> dict:
        return {
            "slow_job": {
                "resource_profile": "heavy",
                "run_count": 4,
                "skip_count": 3,
                "avg_duration_ms": 120.5,
                "max_duration_ms": 260.0,
            },
            "fast_job": {
                "resource_profile": "latency",
                "run_count": 25,
                "skip_count": 0,
                "avg_duration_ms": 4.2,
                "max_duration_ms": 9.1,
            },
        }


def test_format_runner_status_renders_top_jobs() -> None:
    listener = TelegramListener(
        bot_token="token",
        on_signal=lambda signal: None,
        chat_id=None,
        private_chat_ids={123},
        admin_chat_ids={123},
    )
    listener._runner = StubRunner()

    rendered = listener._format_runner_status()

    assert "<b>RUNNER</b>" in rendered
    assert "slow_job" in rendered
    assert "[heavy]" in rendered
    assert "skip=<code>3</code>" in rendered
    assert "avg=<code>120.5ms</code>" in rendered


@pytest.mark.asyncio
async def test_quant_cockpit_disambiguates_prod_readiness_from_blocked_regime(monkeypatch) -> None:
    listener = TelegramListener(
        bot_token="token",
        on_signal=lambda signal: None,
        chat_id=None,
        private_chat_ids={123},
        admin_chat_ids={123},
    )
    monkeypatch.setattr(listener, "_format_runner_status", lambda: "")

    class _Swarm:
        def get_status(self) -> dict:
            return {
                "state": "HEALTHY",
                "production_ready": True,
                "paper_ticks": 478,
                "paper_ticks_required": 100,
                "metrics": {"avg_brier": None},
                "data_gaps": {},
            }

    class _Ledger:
        def get_execution_mode(self) -> str:
            return "PROD"

        def get_capital_summary(self) -> dict:
            return {"total_capital": 11.62}

    listener._ledger = _Ledger()
    listener._resolve_wallet_cockpit_identity = lambda chat_id: ("default", "0xeoa", "0xproxy")
    listener._get_wallet_manager = lambda: SimpleNamespace(
        recuperer_soldes_on_chain=AsyncMock(
            return_value={"usdc_direct": 2.5, "usdc_proxy": 9.12, "eth_balance": 0.01}
        )
    )
    listener._runtime_start = 0
    listener._bot = None
    monkeypatch.setattr("interface.telegram_listener.get_swarm_supervisor", lambda: _Swarm(), raising=False)
    listener._risk = SimpleNamespace(net_beta_exposure_pct=0.0)
    listener._hmm = SimpleNamespace(predict_regime=lambda returns: 2)
    async def _fake_returns():
        return [0.1, -0.1]
    listener._get_btc_returns = _fake_returns
    update = SimpleNamespace(effective_message=SimpleNamespace(chat_id=123))
    listener.reply_to = AsyncMock()

    await listener._cmd_status(update, None)

    text = listener.reply_to.await_args.args[0]
    assert "DEFAULT" in text
    assert "0xproxy" in text
    assert "$11.62" in text
    assert "Direct 2.50" in text
    assert "Proxy 9.12" in text
    assert "Ledger $11.62" in text
    assert "Infra PROD prête" in text
    assert "Trading courant" in text
    assert "BLOQUÉ" in text
    assert "Donnée indisponible" in text
