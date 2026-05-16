import json

from utils.prompt_memory import (
    build_project_prompt_context,
    format_project_prompt_context,
    list_project_memory,
    record_project_memory,
)


def test_record_project_memory_redacts_secret_like_values(tmp_path) -> None:
    memory_path = tmp_path / "project_memory.json"

    entry = record_project_memory(
        component="vault",
        summary="api_key=sk-testsecretsecretsecret should not persist",
        kind="incident",
        tags=["security"],
        path=str(memory_path),
    )

    stored = json.loads(memory_path.read_text())

    assert "sk-testsecretsecretsecret" not in json.dumps(stored)
    assert "<redacted>" in entry["summary"]


def test_list_project_memory_filters_component_and_tag(tmp_path) -> None:
    memory_path = tmp_path / "project_memory.json"
    record_project_memory(
        component="execution",
        summary="Keep maker-first ordering.",
        tags=["risk"],
        path=str(memory_path),
    )
    record_project_memory(
        component="dashboard",
        summary="Read-only by default.",
        tags=["ui"],
        path=str(memory_path),
    )

    entries = list_project_memory(component="exec", tag="risk", path=str(memory_path))

    assert len(entries) == 1
    assert entries[0]["component"] == "execution"


def test_build_project_prompt_context_includes_memory_and_graphify_policy() -> None:
    context = build_project_prompt_context(
        task="Make prompts context-aware",
        specialist_id="mcp_toolsmith",
        component="agent_context",
        token_budget=1800,
    )
    text = format_project_prompt_context(context)

    assert context["specialist"]["id"] == "mcp_toolsmith"
    assert context["project_memory"]
    assert "Graphify" in text
    assert context["estimated_tokens"] <= 1800
