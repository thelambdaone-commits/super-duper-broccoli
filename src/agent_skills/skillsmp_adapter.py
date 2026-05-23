import json
import logging
from typing import Any, Dict, List
from agent_skills.registry import SkillsRegistry

logger = logging.getLogger("SkillsMPAdapter")


class SkillsMPAdapter:
    """
    Adapter complying with the SkillsMP protocol allowing third-party Claude
    or Anthropic orchestrators to leased-out Lobstar's premium quant tools.
    """
    def __init__(self) -> None:
        self.registry = SkillsRegistry()

    def list_rentable_skills(self) -> List[Dict[str, Any]]:
        """Lists rentable quant capabilities with dynamic tool declarations."""
        rentables = []
        for skill in self.registry.list_skills():
            rentables.append({
                "provider": "Lobstar Quant Agentic OS",
                "marketplace_id": f"mp.lobstar.{skill.get('id')}",
                "skill_metadata": skill,
                "pricing": "FREE_OS_RENTAL",
                "compatibility": ["Claude-3.5-Sonnet", "Claude-3-Opus", "OpenClaw"]
            })
        return rentables

    def lease_and_execute_tool(self, skill_id: str, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Leases and dynamically invokes a registered tool, returning a compliant json brief."""
        logger.info(f"SkillsMP: Leasing skill '{skill_id}' for tool '{tool_name}'...")
        try:
            raw_res = self.registry.dispatch_tool(skill_id, tool_name, arguments)
            response = {
                "lease_status": "COMPLETED",
                "provider": "Lobstar Quant Agentic OS",
                "result": raw_res
            }
        except Exception as e:
            logger.error(f"SkillsMP: Tool execution failed: {e}")
            response = {
                "lease_status": "FAILED",
                "provider": "Lobstar Quant Agentic OS",
                "error": str(e)
            }
        return json.dumps(response, indent=2)
