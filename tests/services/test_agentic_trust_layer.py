import pytest

from core.services.agentic_trust_layer import AgenticTraceEvent, AgenticTrustLayer


def test_trust_layer_accepts_extra_incidental_states() -> None:
    layer = AgenticTrustLayer(["ingest", "risk_gate", "ledger_reserve", "execute"])

    result = layer.validate([
        "ingest",
        "loading_noise",
        "risk_gate",
        "telemetry_flush",
        "ledger_reserve",
        "execute",
    ])

    assert result.passed is True
    assert result.missing_states == ()
    assert result.matched_states == ("ingest", "risk_gate", "ledger_reserve", "execute")


def test_trust_layer_rejects_missing_essential_state() -> None:
    layer = AgenticTrustLayer(["ingest", "risk_gate", "ledger_reserve", "execute"])

    result = layer.validate(["ingest", "risk_gate", "execute"])

    assert result.passed is False
    assert result.missing_states == ("ledger_reserve",)


def test_trust_layer_supports_trace_event_objects() -> None:
    layer = AgenticTrustLayer(["start", "finish"])

    result = layer.validate([
        AgenticTraceEvent("start", {"source": "telegram"}),
        AgenticTraceEvent("finish", {"status": "paper"}),
    ])

    assert result.passed is True


def test_trust_layer_derives_common_success_milestones() -> None:
    layer = AgenticTrustLayer.from_success_traces([
        ["ingest", "a", "risk", "ledger", "execute"],
        ["ingest", "b", "risk", "ledger", "notify", "execute"],
        ["ingest", "risk", "ledger", "execute"],
    ])

    assert layer.essential_states == ("ingest", "risk", "ledger", "execute")


def test_trust_layer_requires_success_trace_overlap() -> None:
    with pytest.raises(ValueError):
        AgenticTrustLayer.from_success_traces([["a"], ["b"]])
