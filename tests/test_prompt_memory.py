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


def test_build_project_prompt_context_includes_memory_and_graphify_policy(tmp_path, monkeypatch) -> None:
    memory_path = tmp_path / "project_memory.json"
    monkeypatch.setattr("utils.prompt_memory.PROJECT_MEMORY_PATH", str(memory_path))
    
    record_project_memory(
        component="agent_context",
        summary="Test memory entry.",
        path=str(memory_path)
    )

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


def test_entropy_based_secret_redaction(tmp_path) -> None:
    memory_path = tmp_path / "project_memory.json"

    # Highly random high-entropy hex string (looks like a private key)
    random_hex = "f3a29b8c7d6e5f4a3b2c1d0e9f8a7b6c5d4e3f2a1b0c9d8e7f6a5b4c3d2e1f0a"

    entry = record_project_memory(
        component="execution",
        summary=f"Executing order with key {random_hex}",
        kind="incident",
        tags=["risk"],
        path=str(memory_path),
    )

    assert random_hex not in entry["summary"]
    assert "<redacted_high_entropy_key>" in entry["summary"]
