from pathlib import Path

from services.superpowers_workflow import SuperpowersWorkflow


def test_superpowers_workflow_builds_task_packet() -> None:
    workflow = SuperpowersWorkflow()
    packet = workflow.build_task_packet(goal="Add precise TDD tests for wallet claim")

    payload = packet.as_dict()
    assert payload["goal"] == "Add precise TDD tests for wallet claim"
    assert payload["specialist_id"] == "superpowers_spec_pilot"
    assert payload["context_budget_tokens"] == 3000
    assert "config/project_contexts.json" in payload["priority_files"]
    assert [phase["id"] for phase in payload["phases"]] == [
        "brainstorm",
        "planning",
        "tdd",
        "execution",
        "review",
        "completion",
    ]


def test_superpowers_workflow_rejects_incomplete_report() -> None:
    workflow = SuperpowersWorkflow()
    result = workflow.verify_report({"phase_outputs": {"brainstorm": {"requirements_agreed": "done"}}})

    assert not result.ok
    assert "brainstorm" in result.missing_phase_outputs
    assert "alternatives_considered" in result.missing_phase_outputs["brainstorm"]
    assert "specification" in result.missing_phase_outputs["brainstorm"]
    assert result.missing_guardrails


def test_superpowers_workflow_accepts_complete_report() -> None:
    workflow = SuperpowersWorkflow()
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


def test_superpowers_config_exists_at_path() -> None:
    assert Path("config/superpowers.json").exists()
