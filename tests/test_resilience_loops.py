from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from ai.agents.self_improvement_agent import SelfImprovementAgent
from core.lobstar_cognitive_brain import LobstarCognitiveBrain


class _BrokenArbitrageEngine:
    def detecter_anomalie_kolmogorov(self, outcomes):
        raise RuntimeError("kolm boom")

    def detecter_arbitrage_cross_market(self, primary_market, primary_outcome, secondary_markets):
        raise RuntimeError("cross arb boom")

    def evaluer_legging_risk(self, panier_contrats):
        raise RuntimeError("legging boom")


class _MinimalStore:
    def get_microstructure_range(self, start_ts, end_ts, ticker):
        return []

    def get_feature_history(self, ticker, feature_name, since_ts=0.0, limit=1000):
        return []


class _MinimalScanner:
    client = None


class _MinimalPipeline:
    def latest_features_as_vector(self, ticker):
        return None


@pytest.mark.asyncio
async def test_cognitive_brain_survives_arbitrage_engine_failures(caplog) -> None:
    brain = LobstarCognitiveBrain(
        store=_MinimalStore(),
        scanner=_MinimalScanner(),
        training_pipeline=_MinimalPipeline(),
        arbitrage_engine=_BrokenArbitrageEngine(),
    )

    with caplog.at_level("WARNING"):
        decision = await brain.synthetiser_decision_decision(
            {
                "asset": "SOL",
                "action": "BUY",
                "timestamp": time.time(),
                "outcomes": {"YES": 0.5},
                "panier_contrats": [
                    {
                        "ticker": "SOL",
                        "orderbook": {"bids": [], "asks": []},
                    }
                ],
            }
        )

    assert decision.ticker == "SOL"
    assert decision.arbitrage_edge == 0.0
    assert decision.legging_risk_score == 1.0
    assert "Kolmogorov check failed" in caplog.text
    assert "Cross-market arbitrage check failed" not in caplog.text


def test_self_improvement_falls_back_when_logs_missing(tmp_path: Path, caplog) -> None:
    agent = SelfImprovementAgent(memory_dir=str(tmp_path / "memory"))
    missing_log = tmp_path / "logs" / "missing.log"

    with caplog.at_level("INFO"):
        findings = agent.analyze_logs(str(missing_log))

    assert findings == []
    assert "No log file found for self-improvement scan" in caplog.text
