from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.signal_decision_service import SignalDecisionService


class _RiskEngine:
    def __init__(self) -> None:
        self.calls = []

    async def validate_signal_risk(self, signal, current_portfolio_value: float, active_positions: dict):
        self.calls.append(
            {
                "signal": signal,
                "current_portfolio_value": current_portfolio_value,
                "active_positions": dict(active_positions),
            }
        )
        return True, "OK"


@pytest.mark.asyncio
async def test_apply_portfolio_risk_gate_uses_paper_positions_in_paper_mode() -> None:
    risk_engine = _RiskEngine()
    ledger = SimpleNamespace(
        get_execution_mode=lambda: "PAPER",
        get_capital_summary=lambda: {"total_capital": 100.0, "available_capital": 80.0},
        get_paper_positions=lambda status="OPEN": [
            {"ticker": "SOL", "capital_virtual": 12.0},
            {"ticker": "SOL", "size": 4.0, "entry_price": 0.5},
            {"ticker": "BTC", "capital_virtual": 7.0},
        ],
        get_open_positions=lambda: [{"ticker": "SHOULD_NOT_BE_USED", "capital_engaged": 999.0}],
    )
    service = SignalDecisionService(
        predictive_gate=None,
        risk_engine=risk_engine,
        ledger=ledger,
        snapshot_mgr=SimpleNamespace(),
    )

    ok, reason = await service.apply_portfolio_risk_gate({"ticker": "ETH", "price": 0.5})

    assert ok is True
    assert reason == "OK"
    assert risk_engine.calls[0]["active_positions"] == {"SOL": 14.0, "BTC": 7.0}
