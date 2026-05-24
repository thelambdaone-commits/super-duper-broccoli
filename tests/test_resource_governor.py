from __future__ import annotations

from core.resource_governor import ResourceGovernor, ResourceSnapshot


def test_resource_governor_classifies_constrained_and_critical() -> None:
    governor = ResourceGovernor()

    mode, reasons = governor._classify(85.0, 60.0, None, None)
    assert mode == "constrained"
    assert any(reason.startswith("cpu>=") for reason in reasons)

    mode, reasons = governor._classify(40.0, 91.0, None, None)
    assert mode == "critical"
    assert any(reason.startswith("mem>=") for reason in reasons)


def test_resource_governor_applies_job_policies_from_snapshot() -> None:
    governor = ResourceGovernor()
    governor._snapshot = ResourceSnapshot(0.0, 95.0, 92.0, 2048.0, None, None, "critical", ("cpu>=92",))

    assert governor.should_skip_job("heavy") is True
    assert governor.should_skip_job("latency") is False
    assert governor.interval_multiplier("heavy") >= 6.0
