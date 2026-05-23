from continuous_improvement.skills.base import Skill


class OpenVikingSkill(Skill):
    @property
    def name(self) -> str:
        return "OpenViking"

    @property
    def description(self) -> str:
        return "Optional context-backend skill for OpenViking search-backed project memory retrieval."

    @property
    def priority_files(self) -> list[str]:
        return [
            "utils/openviking_adapter.py",
            "utils/prompt_memory.py",
            "config/openviking.json",
        ]
