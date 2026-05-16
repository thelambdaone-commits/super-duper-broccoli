from utils.project_context import get_project_context, list_project_contexts


def test_token_saving_project_contexts_are_registered() -> None:
    expected_ids = {
        "graphify",
        "claude_mem",
        "everything_claude_code",
        "superpowers",
        "ruflo",
    }

    contexts = {item["id"] for item in list_project_contexts()}

    assert expected_ids.issubset(contexts)


def test_graphify_context_exposes_install_and_guardrails() -> None:
    context = get_project_context("graphify")

    assert context["package"] == "graphifyy"
    assert "graphify install --platform codex" in context["install"]
    assert "graphify update ." in context["install"]
    assert any(".graphifyignore" in guardrail for guardrail in context["required_guardrails"])
