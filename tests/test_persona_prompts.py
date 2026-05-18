import json

import pytest

from utils.persona_prompts import (
    build_llm_council_question_from_personas,
    build_multi_persona_packet,
    build_persona_prompt,
    list_personas,
    load_persona_prompt_config,
)


def test_persona_config_contains_required_roles() -> None:
    persona_ids = {persona["id"] for persona in list_personas()}

    assert {
        "trader",
        "coder",
        "ml",
        "strategist",
        "analyst",
        "actuary",
        "llm_council_chair",
        "mirofish_swarm",
        "ruflo_orchestrator",
        "superpowers_spec_pilot",
    }.issubset(persona_ids)


def test_build_persona_prompt_redacts_secret_like_context() -> None:
    prompt = build_persona_prompt(
        "trader",
        "Analyze sk-or-secretvalue setup",
        context={"raw": "token gsk_secretvalue"},
    )

    assert prompt["persona_id"] == "trader"
    assert "sk-or-[REDACTED]" in prompt["prompt"]
    assert "gsk_[REDACTED]" in prompt["prompt"]
    assert "secretvalue" not in prompt["prompt"]
    assert "portfolio_risk_engine" in " ".join(prompt["guardrails"])


def test_multi_persona_packet_builds_trading_decision_profile() -> None:
    packet = build_multi_persona_packet("Assess a SOL market", profile="trading_decision")

    assert packet["persona_ids"] == ["trader", "strategist", "analyst", "actuary", "ml"]
    assert "core/portfolio_risk_engine.py" in packet["priority_files"]
    assert packet["llm_council"]["chair_persona"] == "llm_council_chair"
    assert packet["mirofish"]["persona"] == "mirofish_swarm"
    assert packet["ruflo"]["persona"] == "ruflo_orchestrator"
    assert packet["superpowers"]["persona"] == "superpowers_spec_pilot"


def test_multi_persona_packet_can_generate_council_question() -> None:
    packet = build_multi_persona_packet(
        "Implement wallet tracking",
        persona_ids=["coder", "analyst", "actuary"],
    )
    question = build_llm_council_question_from_personas(packet)

    assert "coder" in question
    assert "actuary" in question
    assert "deterministic verification gates" in question


def test_unknown_persona_is_rejected() -> None:
    with pytest.raises(ValueError):
        build_persona_prompt("unknown", "task")


def test_persona_config_is_json_serializable() -> None:
    config = load_persona_prompt_config()

    assert json.loads(json.dumps(config))["version"] == 1
