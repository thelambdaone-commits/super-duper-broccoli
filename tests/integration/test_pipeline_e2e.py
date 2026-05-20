from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from core.orchestrator import LobstarOrchestrator
from core.services.circuit_breaker import CircuitBreakerConfig, CircuitBreakerService
from core.services.predictive_gate import PredictiveGateConfig, PredictiveGateService
from core.services.signal_router import SignalRouter


class FakeSnapshotManager:
    def __init__(self) -> None:
        self.captures: list[dict] = []

    def capture(self, **kwargs) -> None:
        self.captures.append(dict(kwargs))


class FakeNotifier:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def send(self, message: str, parse_mode: str = "Markdown") -> bool:
        self.messages.append(message)
        return True


class FakeMetricsExporter:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def log_execution(self, signal, report: dict) -> None:
        self.calls.append({"signal": dict(signal), "report": dict(report)})


class FakeHMM:
    def predict_with_label(self, returns):
        return None, "LOW_VOLATILITY"


class FakeCognitiveBrain:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def synthesize_cognitive_decision(self, signal: dict):
        self.calls.append(dict(signal))
        microstructure = signal.get("microstructure_context") or {}
        return SimpleNamespace(
            reason="synthetic-e2e",
            action="EXECUTE",
            microstructure_regime=str(microstructure.get("liquidity_regime") or "UNKNOWN").upper(),
            observed_liquidity_score=float(microstructure.get("liquidity_score", 0.0) or 0.0),
            take_profit_bias=float(microstructure.get("take_profit_bias", 0.0) or 0.0),
            stop_loss_bias=float(microstructure.get("stop_loss_bias", 0.0) or 0.0),
            spread_bps=float(microstructure.get("spread_bps", 0.0) or 0.0),
            order_imbalance=float(microstructure.get("order_imbalance", 0.0) or 0.0),
        )

    def enrich_signal(self, signal: dict, decision):
        enriched = dict(signal)
        enriched["cognitive_reason"] = decision.reason
        enriched["cognitive_decision"] = {
            "action": getattr(decision, "action", "EXECUTE"),
            "reason": decision.reason,
            "microstructure_regime": getattr(decision, "microstructure_regime", "UNKNOWN"),
            "observed_liquidity_score": getattr(decision, "observed_liquidity_score", 0.0),
            "take_profit_bias": getattr(decision, "take_profit_bias", 0.0),
            "stop_loss_bias": getattr(decision, "stop_loss_bias", 0.0),
            "spread_bps": getattr(decision, "spread_bps", 0.0),
            "order_imbalance": getattr(decision, "order_imbalance", 0.0),
        }
        enriched["status"] = "ENRICHED"
        return enriched


class FakeBroadcaster:
    def __init__(self) -> None:
        self.signal_messages: list[dict] = []
        self.risk_messages: list[dict] = []

    async def diffuser_signal_au_canal(self, data: dict) -> bool:
        self.signal_messages.append(dict(data))
        return True

    async def diffuser_alerte_risque_au_canal(self, alert_data: dict) -> bool:
        self.risk_messages.append(dict(alert_data))
        return True


class FakeListener:
    def __init__(self) -> None:
        self.replies: list[dict] = []
        self.sent: list[dict] = []

    async def reply_to(self, confirmation: str, update, parse_mode: str = "HTML") -> bool:
        self.replies.append({"confirmation": confirmation, "update": update, "parse_mode": parse_mode})
        return True

    async def send_message(self, text: str, chat_id=None, parse_mode: str = "HTML") -> bool:
        self.sent.append({"text": text, "chat_id": chat_id, "parse_mode": parse_mode})
        return True


class FakeRiskEngine:
    def __init__(self, allowed: bool = True, reason: str = "Risk constraints validated successfully") -> None:
        self.allowed = allowed
        self.reason = reason
        self.calls: list[dict] = []

    async def validate_signal_risk(self, signal, current_portfolio_value: float, active_positions: dict):
        self.calls.append(
            {
                "signal": dict(signal),
                "current_portfolio_value": current_portfolio_value,
                "active_positions": dict(active_positions),
            }
        )
        return self.allowed, self.reason


class FakeRegexExecutor:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def __call__(self, signal: dict, ledger, freqai, **kwargs):
        self.calls.append({"signal": dict(signal), "kwargs": dict(kwargs)})
        return {
            "status": "SUCCESS",
            "trade_id": "e2e-trade-1",
            "ticker": signal.get("ticker", "SOL"),
            "side": signal.get("side", "BUY"),
            "executed_size": 12.5,
            "price": 0.72,
        }


def _build_orchestrator(
    *,
    predictive_allowed: bool = True,
    predictive_reason: str = "ACCEPT_PREDICTIVE_EDGE",
    risk_allowed: bool = True,
    risk_reason: str = "Risk constraints validated successfully",
    route_result: dict | None = None,
    route_exception: Exception | None = None,
):
    fake_executor = SimpleNamespace(
        get_execution_mode=lambda: "PAPER",
    )
    container = SimpleNamespace(
        ledger=SimpleNamespace(),
        freqai=SimpleNamespace(),
        risk=FakeRiskEngine(allowed=risk_allowed, reason=risk_reason),
        hmm=FakeHMM(),
        store=SimpleNamespace(),
        executor=fake_executor,
        notifier=FakeNotifier(),
        metrics_exporter=FakeMetricsExporter(),
    )
    snapshot_mgr = FakeSnapshotManager()
    broadcaster = FakeBroadcaster()
    listener = FakeListener()
    cognitive_brain = FakeCognitiveBrain()
    regex_executor = FakeRegexExecutor()

    class _RouteExecutor:
        async def execute(self, signal: dict, context):
            regex_executor.calls.append({"signal": dict(signal), "kwargs": {"tenant_wallet": context.tenant_wallet}})
            if route_exception is not None:
                raise route_exception
            if route_result is not None:
                return dict(route_result)
            return {
                "status": "SUCCESS",
                "trade_id": "e2e-trade-1",
                "ticker": signal.get("ticker", "SOL"),
                "side": signal.get("side", "BUY"),
                "executed_size": 12.5,
                "price": 0.72,
            }

    router = SignalRouter(
        passive_executor=_RouteExecutor(),
        active_executor=_RouteExecutor(),
        arbitrage_executor=_RouteExecutor(),
    )

    predictive_gate = PredictiveGateService(
        PredictiveGateConfig(min_edge_threshold=0.07, allow_simulated_gate=False),
        model_registry=SimpleNamespace(
            predict_winning_bet=lambda df_market_ticks, clob_price_yes, timestamp_resolution: {
                "pari_approuve": predictive_allowed,
                "probability_win": 0.81,
                "absolute_edge": 0.14,
            }
        ),
    )
    if not predictive_allowed:
        predictive_gate._validate_simulated = lambda signal: (False, predictive_reason)

    circuit_breaker = CircuitBreakerService(CircuitBreakerConfig(failure_threshold=2, recovery_timeout_seconds=60))
    orchestrator = LobstarOrchestrator(
        container=container,
        secrets={"TELEGRAM_BOT_TOKEN": "x"},
        execution_mode="PAPER",
        listener=listener,
        circuit_breaker=circuit_breaker,
        snapshot_mgr=snapshot_mgr,
        cognitive_brain=cognitive_brain,
        copy_trading_agent=None,
        market_scanner=SimpleNamespace(),
        lobstar_agent=None,
        access_control=SimpleNamespace(obtenir_wallet_associe=lambda chat_id: "wallet-1"),
        broadcaster=broadcaster,
        predictive_gate_service=predictive_gate,
        signal_router=router,
    )

    return orchestrator, container, snapshot_mgr, broadcaster, listener, cognitive_brain, regex_executor, circuit_breaker, container.risk


@pytest.mark.asyncio
async def test_pipeline_e2e_signal_flows_through_services(monkeypatch: pytest.MonkeyPatch) -> None:
    orchestrator, container, snapshot_mgr, broadcaster, listener, _, regex_executor, _, risk_engine = _build_orchestrator()
    orchestrator.start()
    signal = {
        "ticker": "SOL",
        "side": "BUY",
        "price": 0.65,
        "source": "regex",
        "chat_id": 12345,
        "microstructure_context": {
            "liquidity_regime": "LIQUID",
            "liquidity_score": 0.88,
            "take_profit_bias": 0.12,
            "stop_loss_bias": -0.04,
            "spread_bps": 18.0,
            "order_imbalance": 0.22,
        },
        "market_features": {
            "price": [0.65],
            "volume": [150.0],
            "bid_depth": [80.0],
            "ask_depth": [70.0],
        },
    }

    await orchestrator.on_signal(signal)
    await asyncio.sleep(0.05)
    await orchestrator.stop()

    assert snapshot_mgr.captures
    assert snapshot_mgr.captures[0]["category"] == "TRADING"
    assert broadcaster.signal_messages
    assert broadcaster.signal_messages[0]["ticker"] == "SOL"
    assert regex_executor.calls
    assert regex_executor.calls[0]["kwargs"]["tenant_wallet"] == "wallet-1"
    assert any("Décision Lobstar Cognitive Brain" in message for message in container.notifier.messages)
    assert any("Régime CLOB" in message for message in container.notifier.messages)
    assert listener.sent
    assert "TRADE CONFIRMED" in listener.sent[0]["text"] or "TRADE CONFIRMED" in listener.sent[-1]["text"]
    assert container.notifier.messages
    assert "Trade Executed" in container.notifier.messages[-1]
    assert orchestrator.circuit_breaker_service.state.value == "CLOSED"
    assert signal["predictive_probability"] == 0.81
    assert signal["predictive_edge"] == 0.14
    assert risk_engine.calls


@pytest.mark.asyncio
async def test_pipeline_e2e_twap_execution_report_is_notified(monkeypatch: pytest.MonkeyPatch) -> None:
    orchestrator, container, snapshot_mgr, broadcaster, listener, _, regex_executor, _, _ = _build_orchestrator(
        route_result={
            "status": "SUCCESS",
            "strategy": "TWAP",
            "trade_id": "twap-trade-1",
            "ticker": "SOL",
            "side": "BUY",
            "executed_size": 30.0,
            "price": 0.61,
            "slices_attempted": 4,
            "slices_filled": 4,
            "total_filled_usd": 30.0,
            "avg_market_volume_observed": 120.0,
            "realized_participation_rate": 0.25,
            "volume_capped_events": 2,
            "execution_preference": "PASSIVE_ONLY",
        }
    )
    orchestrator.start()
    signal = {
        "ticker": "SOL",
        "side": "BUY",
        "price": 0.61,
        "source": "regex",
        "chat_id": 12345,
        "market_features": {
            "price": [0.61],
            "volume": [120.0],
            "bid_depth": [200.0],
            "ask_depth": [180.0],
        },
    }

    await orchestrator.on_signal(signal)
    await asyncio.sleep(0.05)
    await orchestrator.stop()

    assert container.notifier.messages
    last_message = container.notifier.messages[-1]
    assert "TWAP" in last_message
    assert "PR Réalisé" in last_message
    assert "Tranches" in last_message
    assert "Limitation Vol." in last_message


@pytest.mark.asyncio
async def test_pipeline_e2e_exports_execution_metrics() -> None:
    orchestrator, container, *_ = _build_orchestrator()
    orchestrator.start()
    signal = {
        "ticker": "SOL",
        "side": "BUY",
        "price": 0.61,
        "source": "regex",
        "chat_id": 12345,
        "market_features": {
            "price": [0.61],
            "volume": [120.0],
            "bid_depth": [200.0],
            "ask_depth": [180.0],
        },
    }

    await orchestrator.on_signal(signal)
    await asyncio.sleep(0.05)
    await orchestrator.stop()

    assert container.metrics_exporter.calls
    payload = container.metrics_exporter.calls[-1]["report"]
    assert payload["status"] == "SUCCESS"
    assert payload["ticker"] == "SOL"


@pytest.mark.asyncio
async def test_pipeline_e2e_circuit_breaker_tripped(monkeypatch: pytest.MonkeyPatch) -> None:
    orchestrator, container, snapshot_mgr, broadcaster, listener, _, regex_executor, circuit_breaker, _ = _build_orchestrator()
    circuit_breaker.state = circuit_breaker.state.OPEN
    circuit_breaker.last_failure_time = None
    circuit_breaker.check_signal = lambda signal: False
    orchestrator.start()

    await orchestrator.on_signal({"ticker": "SOL", "side": "BUY", "source": "regex", "chat_id": 12345})
    await asyncio.sleep(0.05)
    await orchestrator.stop()

    assert snapshot_mgr.captures == []
    assert broadcaster.risk_messages
    assert regex_executor.calls == []
    assert container.notifier.messages
    assert "CIRCUIT BREAKER OPEN" in container.notifier.messages[-1]


@pytest.mark.asyncio
async def test_pipeline_e2e_predictive_gate_rejection(monkeypatch: pytest.MonkeyPatch) -> None:
    orchestrator, container, snapshot_mgr, broadcaster, listener, _, regex_executor, circuit_breaker, _ = _build_orchestrator(
        predictive_allowed=False,
        predictive_reason="Score de confiance insuffisant",
    )
    circuit_breaker.check_signal = lambda signal: True
    orchestrator.start()

    signal = {
        "ticker": "SOL",
        "side": "BUY",
        "source": "regex",
        "chat_id": 12345,
        "simulated_edge": 0.01,
    }
    await orchestrator.on_signal(signal)
    await asyncio.sleep(0.05)
    await orchestrator.stop()

    assert snapshot_mgr.captures
    assert broadcaster.signal_messages == []
    assert regex_executor.calls == []
    assert listener.sent == []
    assert "predictive_probability" not in signal
    assert "predictive_edge" not in signal


@pytest.mark.asyncio
async def test_pipeline_e2e_routing_failure_or_agent_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    orchestrator, container, snapshot_mgr, broadcaster, listener, _, regex_executor, circuit_breaker, _ = _build_orchestrator(
        route_exception=RuntimeError("router exploded"),
    )
    recorded_failures: list[str] = []
    circuit_breaker.record_failure = lambda error: recorded_failures.append(str(error))
    orchestrator.start()

    await orchestrator.on_signal(
        {
            "ticker": "SOL",
            "side": "BUY",
            "source": "regex",
            "chat_id": 12345,
            "market_features": {
                "price": [0.65],
                "volume": [150.0],
                "bid_depth": [80.0],
                "ask_depth": [70.0],
            },
        }
    )
    await asyncio.sleep(0.05)
    await orchestrator.stop()

    assert snapshot_mgr.captures
    assert regex_executor.calls
    assert broadcaster.signal_messages
    assert recorded_failures
    assert "router exploded" in recorded_failures[-1]
    assert listener.sent == []


@pytest.mark.asyncio
async def test_pipeline_e2e_portfolio_risk_rejection(monkeypatch: pytest.MonkeyPatch) -> None:
    orchestrator, container, snapshot_mgr, broadcaster, listener, _, regex_executor, _, risk_engine = _build_orchestrator(
        risk_allowed=False,
        risk_reason="Risk Circuit Breaker: Max Trailing Drawdown breached (6.00%)",
    )
    orchestrator.start()

    await orchestrator.on_signal(
        {
            "ticker": "BTC",
            "side": "BUY",
            "source": "regex",
            "chat_id": 12345,
            "market_features": {
                "price": [0.65],
                "volume": [150.0],
                "bid_depth": [80.0],
                "ask_depth": [70.0],
            },
        }
    )
    await asyncio.sleep(0.05)
    await orchestrator.stop()

    assert snapshot_mgr.captures
    assert risk_engine.calls
    assert broadcaster.signal_messages == []
    assert regex_executor.calls == []
    assert listener.sent == []
    assert container.notifier.messages
    assert "Risk Circuit Breaker" in container.notifier.messages[-1]
