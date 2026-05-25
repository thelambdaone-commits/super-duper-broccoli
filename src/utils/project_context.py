import json
import os
from functools import lru_cache
from typing import Any, Optional


PROJECT_CONTEXT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "config",
    "project_contexts.json",
)


@lru_cache(maxsize=1)
def load_project_contexts(path: str = PROJECT_CONTEXT_PATH) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def list_project_contexts(category: Optional[str] = None) -> list[dict[str, Any]]:
    data = load_project_contexts()
    projects = data.get("projects", [])
    if category:
        projects = [p for p in projects if p.get("category") == category]
    return [
        {
            "id": p.get("id"),
            "name": p.get("name"),
            "category": p.get("category"),
            "status": p.get("status"),
            "repo": p.get("repo"),
        }
        for p in projects
    ]


def get_project_context(project_id: str) -> dict[str, Any]:
    normalized = project_id.strip().lower().replace("-", "_")
    data = load_project_contexts()
    for project in data.get("projects", []):
        aliases = {
            str(project.get("id", "")).lower(),
            str(project.get("name", "")).lower().replace(" ", "_").replace("-", "_"),
        }
        if normalized in aliases:
            return project
    return {
        "error": f"Unknown project context: {project_id}",
        "available": [p.get("id") for p in data.get("projects", [])],
    }


def list_local_skill_contexts() -> list[dict[str, Any]]:
    return load_project_contexts().get("local_skills", [])
