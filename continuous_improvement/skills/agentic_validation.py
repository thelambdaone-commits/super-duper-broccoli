from __future__ import annotations

from typing import Any, Optional

from continuous_improvement.skills.base import Skill


class AgenticValidationSkill(Skill):
    @property
    def name(self) -> str:
        return "agentic_validation"

    @property
    def description(self) -> str:
        return "Validates non-deterministic agent workflows with essential milestones instead of brittle scripts"

    @property
    def priority_files(self) -> list[str]:
        return [
            "core/services/agentic_trust_layer.py",
            "config/trading_agents_playbook.json",
            "tests/services/test_agentic_trust_layer.py",
        ]

    def suggest_improvements(self, paths: Optional[list[str]] = None) -> list[dict[str, Any]]:
        return [
            {
                "component": "agentic_traces",
                "suggestion": "Emit trace milestones from orchestrator, risk, ledger, and execution handoffs.",
                "priority": "high",
                "impact": "Enables structural validation of successful trading workflows without requiring identical execution paths.",
            },
            {
                "component": "ci",
                "suggestion": "Validate paper-trading traces against config/trading_agents_playbook.json before promoting strategies.",
                "priority": "high",
                "impact": "Catches missing risk or ledger milestones even when final outputs look plausible.",
            },
        ]
