import json
import os
from functools import lru_cache
from typing import Any

from utils.prompt_memory import build_project_prompt_context


CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "config")
AI_SPECIALISTS_PATH = os.path.join(CONFIG_DIR, "ai_specialists.json")
FREE_PROVIDER_SOURCES_PATH = os.path.join(CONFIG_DIR, "free_ai_provider_sources.json")


@lru_cache(maxsize=1)
def load_ai_specialists(path: str = AI_SPECIALISTS_PATH) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def load_free_provider_sources(path: str = FREE_PROVIDER_SOURCES_PATH) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def list_ai_specialists(task: str = "") -> list[dict[str, Any]]:
    data = load_ai_specialists()
    task_norm = task.strip().lower()
    specialists = data.get("specialists", [])
    if task_norm:
        specialists = [
            s for s in specialists
            if any(task_norm in t.lower() for t in s.get("tasks", []))
            or task_norm in s.get("id", "").lower()
            or task_norm in s.get("name", "").lower()
        ]
    return [
        {
            "id": s.get("id"),
            "name": s.get("name"),
            "tasks": s.get("tasks", []),
            "provider_policy": s.get("provider_policy"),
            "priority_files": s.get("priority_files", []),
        }
        for s in specialists
    ]


def get_ai_specialist(specialist_id: str) -> dict[str, Any]:
    normalized = specialist_id.strip().lower().replace("-", "_")
    for specialist in load_ai_specialists().get("specialists", []):
        if normalized == specialist.get("id", "").lower():
            return specialist
    return {
        "error": f"Unknown AI specialist: {specialist_id}",
        "available": [s.get("id") for s in load_ai_specialists().get("specialists", [])],
    }


def get_ai_routing_policy() -> dict[str, Any]:
    return load_ai_specialists().get("routing_policy", {})


def list_free_ai_provider_sources() -> dict[str, Any]:
    return load_free_provider_sources()


def build_specialist_prompt_context(specialist_id: str) -> dict[str, Any]:
    specialist = get_ai_specialist(specialist_id)
    if "error" in specialist:
        return specialist
    context_budget = get_ai_routing_policy().get("default_context_budget_tokens", 2500)
    return {
        "specialist": specialist,
        "routing_policy": get_ai_routing_policy(),
        "context_budget_tokens": context_budget,
        "project_prompt_context": build_project_prompt_context(
            task=", ".join(specialist.get("tasks", [])[:4]),
            specialist_id=specialist_id,
            component="",
            token_budget=context_budget,
        ),
        "instruction": "Use project_prompt_context, priority_files, context cards, and Graphify first. Do not request whole-repo dumps unless strictly necessary.",
    }
