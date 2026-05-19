import importlib.util
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("SkillsRegistry")

SKILLS_DIR = Path(__file__).resolve().parent


class SkillsRegistry:
    def __init__(self, skills_dir: Path = SKILLS_DIR) -> None:
        self.skills_dir = skills_dir
        self.skills: Dict[str, Dict[str, Any]] = {}
        self._module_cache: Dict[str, Any] = {}
        self.load_skills()

    def load_skills(self) -> None:
        """Discovers and hot-reloads all valid skills in the directory."""
        self.skills.clear()
        self._module_cache.clear()
        if not self.skills_dir.exists():
            return

        for entry in self.skills_dir.iterdir():
            if entry.is_dir() and not entry.name.startswith("_") and entry.name != "scratch":
                manifest_path = entry / "skill.json"
                entrypoint_path = entry / "entrypoint.py"

                if manifest_path.exists() and entrypoint_path.exists():
                    try:
                        with open(manifest_path, "r", encoding="utf-8") as f:
                            manifest = json.load(f)

                        skill_id = manifest.get("id", entry.name)
                        self.skills[skill_id] = {
                            "manifest": manifest,
                            "entrypoint": entrypoint_path,
                            "dir": entry,
                        }
                        logger.info(f"Loaded Agent Skill: {skill_id} v{manifest.get('version', '1.0.0')}")
                    except Exception as e:
                        logger.error(f"Failed to load skill manifest in {entry.name}: {e}")

    def list_skills(self) -> List[Dict[str, Any]]:
        """Returns metadata for all active skills."""
        return [skill["manifest"] for skill in self.skills.values()]

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Compiles OpenAI/Anthropic tool schemas for all dynamic tools."""
        definitions = []
        for skill in self.skills.values():
            tools = skill["manifest"].get("tools", [])
            for tool in tools:
                definitions.append(tool)
        return definitions

    def dispatch_tool(self, skill_id: str, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Dynamically imports a skill entrypoint (with caching) and dispatches arguments to the tool handler."""
        if skill_id not in self.skills:
            raise ValueError(f"Skill {skill_id} not found in registry.")

        if skill_id in self._module_cache:
            module = self._module_cache[skill_id]
        else:
            entrypoint_path = self.skills[skill_id]["entrypoint"]

            # Import entrypoint dynamically
            spec = importlib.util.spec_from_file_location(f"skills_{skill_id}", entrypoint_path)
            if spec is None or spec.loader is None:
                raise ImportError(f"Could not load entrypoint spec for skill {skill_id}")

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self._module_cache[skill_id] = module

        # Execute target tool function
        if not hasattr(module, tool_name):
            raise AttributeError(f"Tool {tool_name} not implemented in skill {skill_id} entrypoint.")

        handler = getattr(module, tool_name)
        return handler(**arguments)
