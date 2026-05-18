from pathlib import Path

from core.services.gsd_workflow import GSDWorkflow


def test_gsd_workflow_builds_compact_task_packet() -> None:
    workflow = GSDWorkflow()
    packet = workflow.build_task_packet(goal="Add a precise Polymarket wallet journal")

    payload = packet.as_dict()
    assert payload["goal"] == "Add a precise Polymarket wallet journal"
    assert payload["specialist_id"] == "project_fusion_architect"
    assert payload["context_budget_tokens"] <= 2500
    assert "config/project_contexts.json" in payload["priority_files"]
    assert [phase["id"] for phase in payload["phases"]] == [
        "intake",
        "context",
        "implementation",
        "verification",
        "handoff",
    ]


def test_gsd_workflow_rejects_incomplete_report() -> None:
    workflow = GSDWorkflow()
    result = workflow.verify_report({"phase_outputs": {"intake": {"goal": "x"}}})

    assert not result.ok
    assert "intake" in result.missing_phase_outputs
    assert "scope" in result.missing_phase_outputs["intake"]
    assert result.missing_guardrails


def test_gsd_workflow_accepts_complete_report() -> None:
    workflow = GSDWorkflow()
    phase_outputs = {}
    for phase in workflow.config["phases"]:
        phase_outputs[phase["id"]] = {output: "ok" for output in phase["required_outputs"]}

    result = workflow.verify_report(
        {
            "phase_outputs": phase_outputs,
            "honored_guardrails": workflow.config["guardrails"],
        }
    )

    assert result.ok
    assert result.missing_phase_outputs == {}
    assert result.missing_guardrails == []


def test_gsd_config_exists_at_documented_path() -> None:
    assert Path("config/gsd_operating_system.json").exists()
