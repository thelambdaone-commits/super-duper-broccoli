from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence


DEFAULT_SUPERPOWERS_CONFIG_PATH = Path("config/superpowers.json")


@dataclass(frozen=True)
class SuperpowersPhase:
    id: str
    purpose: str
    required_outputs: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class SuperpowersTaskPacket:
    goal: str
    specialist_id: str
    context_budget_tokens: int
    priority_files: tuple[str, ...]
    phases: tuple[SuperpowersPhase, ...]
    guardrails: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "specialist_id": self.specialist_id,
            "context_budget_tokens": self.context_budget_tokens,
            "priority_files": list(self.priority_files),
            "phases": [
                {
                    "id": phase.id,
                    "purpose": phase.purpose,
                    "required_outputs": list(phase.required_outputs),
                }
                for phase in self.phases
            ],
            "guardrails": list(self.guardrails),
        }


@dataclass(frozen=True)
class SuperpowersVerificationResult:
    ok: bool
    missing_phase_outputs: dict[str, list[str]]
    missing_guardrails: list[str]


class SuperpowersWorkflow:
    """Spec-driven, TDD-oriented task packet builder and verification engine for Superpowers workflow."""

    def __init__(self, config_path: str | Path = DEFAULT_SUPERPOWERS_CONFIG_PATH) -> None:
        self.config_path = Path(config_path)
        self.config = self._load_config(self.config_path)

    @staticmethod
    def _load_config(path: Path) -> dict[str, Any]:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def build_task_packet(
        self,
        *,
        goal: str,
        specialist_id: str = "superpowers_spec_pilot",
        priority_files: Sequence[str] | None = None,
    ) -> SuperpowersTaskPacket:
        if not goal.strip():
            raise ValueError("goal must not be empty")

        phases = tuple(
            SuperpowersPhase(
                id=str(item["id"]),
                purpose=str(item["purpose"]),
                required_outputs=tuple(str(output) for output in item.get("required_outputs", [])),
            )
            for item in self.config.get("phases", [])
        )
        return SuperpowersTaskPacket(
            goal=goal.strip(),
            specialist_id=specialist_id,
            context_budget_tokens=int(self.config.get("context_budget_tokens", 3000)),
            priority_files=tuple(priority_files or self.config.get("default_priority_files", [])),
            phases=phases,
            guardrails=tuple(str(item) for item in self.config.get("guardrails", [])),
        )

    def verify_report(self, report: Mapping[str, Any]) -> SuperpowersVerificationResult:
        phase_outputs = report.get("phase_outputs", {})
        honored_guardrails = {str(item) for item in report.get("honored_guardrails", [])}

        missing_phase_outputs: dict[str, list[str]] = {}
        for phase in self.config.get("phases", []):
            phase_id = str(phase["id"])
            outputs = phase_outputs.get(phase_id, {})
            if not isinstance(outputs, Mapping):
                outputs = {}
            missing = [
                str(output)
                for output in phase.get("required_outputs", [])
                if not outputs.get(str(output))
            ]
            if missing:
                missing_phase_outputs[phase_id] = missing

        required_guardrails = [str(item) for item in self.config.get("guardrails", [])]
        missing_guardrails = [item for item in required_guardrails if item not in honored_guardrails]
        return SuperpowersVerificationResult(
            ok=not missing_phase_outputs and not missing_guardrails,
            missing_phase_outputs=missing_phase_outputs,
            missing_guardrails=missing_guardrails,
        )
