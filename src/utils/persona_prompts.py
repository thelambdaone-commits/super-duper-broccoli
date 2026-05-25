from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any, Mapping, Sequence

from utils.llm_council import _redact_secret_like_text


CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "config")
PERSONA_PROMPTS_CONFIG_PATH = os.path.join(CONFIG_DIR, "persona_prompts.json")


@lru_cache(maxsize=1)
def load_persona_prompt_config(path: str = PERSONA_PROMPTS_CONFIG_PATH) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _persona_index(config: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(persona["id"]): dict(persona) for persona in config.get("personas", [])}


def list_personas(config: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    cfg = config or load_persona_prompt_config()
    return [
        {
            "id": persona["id"],
            "name": persona["name"],
            "domain": persona["domain"],
            "output_contract": persona.get("output_contract", []),
        }
        for persona in cfg.get("personas", [])
    ]


def build_persona_prompt(
    persona_id: str,
    task: str,
    *,
    context: Mapping[str, Any] | None = None,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = config or load_persona_prompt_config()
    personas = _persona_index(cfg)
    if persona_id not in personas:
        raise ValueError(f"Unknown persona_id={persona_id}")

    persona = personas[persona_id]
    safe_task = _redact_secret_like_text(task.strip())
    safe_context = {
        str(key): _redact_secret_like_text(str(value))[:1000]
        for key, value in (context or {}).items()
    }
    global_guardrails = list(cfg.get("global_guardrails", []))
    verification = list(cfg.get("prompt_template", {}).get("verification", []))
    prompt = "\n\n".join(
        [
            f"ROLE:\n{persona['system_prompt']}",
            "GLOBAL GUARDRAILS:\n" + "\n".join(f"- {item}" for item in global_guardrails),
            f"TASK:\n{safe_task}",
            "AVAILABLE CONTEXT:\n"
            + (json.dumps(safe_context, indent=2, sort_keys=True) if safe_context else "No extra context provided."),
            "FOCUS:\n" + "\n".join(f"- {item}" for item in persona.get("focus", [])),
            "OUTPUT CONTRACT:\n" + "\n".join(f"- {item}" for item in persona.get("output_contract", [])),
            "VERIFICATION:\n" + "\n".join(f"- {item}" for item in verification),
        ]
    )
    return {
        "persona_id": persona_id,
        "name": persona["name"],
        "domain": persona["domain"],
        "prompt": prompt,
        "priority_files": persona.get("priority_files", []),
        "output_contract": persona.get("output_contract", []),
        "guardrails": global_guardrails,
    }


def build_multi_persona_packet(
    task: str,
    *,
    profile: str = "trading_decision",
    persona_ids: Sequence[str] | None = None,
    context: Mapping[str, Any] | None = None,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = config or load_persona_prompt_config()
    selected = list(persona_ids or cfg.get("council_profiles", {}).get(profile, []))
    if not selected:
        raise ValueError(f"No personas configured for profile={profile}")

    persona_prompts = [
        build_persona_prompt(persona_id, task, context=context, config=cfg)
        for persona_id in selected
    ]
    priority_files: list[str] = []
    for item in persona_prompts:
        for path in item.get("priority_files", []):
            if path not in priority_files:
                priority_files.append(path)

    return {
        "profile": profile,
        "task": _redact_secret_like_text(task.strip()),
        "persona_ids": selected,
        "personas": persona_prompts,
        "priority_files": priority_files,
        "llm_council": {
            "mode": "independent_opinion_then_review_then_chairman",
            "chair_persona": "llm_council_chair",
            "config": "config/llm_council.json",
        },
        "mirofish": {
            "mode": "bounded_swarm_research_only",
            "persona": "mirofish_swarm",
            "config": "config/mirofish.json",
        },
        "ruflo": {
            "mode": "bounded_agent_dag_with_file_ownership",
            "persona": "ruflo_orchestrator",
            "config": "ruflo_config.json",
        },
        "superpowers": {
            "mode": "local_methodology_adapter",
            "persona": "superpowers_spec_pilot",
            "config": "config/superpowers.json",
        },
        "guardrails": cfg.get("global_guardrails", []),
    }


def build_llm_council_question_from_personas(packet: Mapping[str, Any]) -> str:
    contracts = []
    for persona in packet.get("personas", []):
        contracts.append(
            {
                "persona_id": persona.get("persona_id"),
                "name": persona.get("name"),
                "domain": persona.get("domain"),
                "output_contract": persona.get("output_contract", []),
            }
        )
    return (
        "Run a multi-persona council for this task.\n"
        f"Task: {_redact_secret_like_text(str(packet.get('task', '')))}\n"
        f"Personas and output contracts:\n{json.dumps(contracts, indent=2, sort_keys=True)}\n"
        "Return consensus, dissent, risks, and deterministic verification gates."
    )
