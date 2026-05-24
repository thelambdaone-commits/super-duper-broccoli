from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence


@dataclass(frozen=True)
class AgenticTraceEvent:
    """A semantic milestone emitted by an agentic workflow."""

    state: str
    metadata: Mapping[str, object] | None = None


@dataclass(frozen=True)
class AgenticValidationResult:
    passed: bool
    missing_states: tuple[str, ...]
    out_of_order_states: tuple[str, ...]
    matched_states: tuple[str, ...]


class AgenticTrustLayer:
    """
    Validates non-deterministic agent traces by checking essential milestones.

    This intentionally avoids record-and-replay exact matching. Extra states are
    treated as incidental noise; required states must appear in order.
    """

    def __init__(self, essential_states: Sequence[str]) -> None:
        if not essential_states:
            raise ValueError("essential_states must not be empty")
        self.essential_states = tuple(essential_states)

    @classmethod
    def from_success_traces(cls, traces: Sequence[Sequence[str]]) -> "AgenticTrustLayer":
        if not traces:
            raise ValueError("at least one success trace is required")

        common = set(traces[0])
        for trace in traces[1:]:
            common &= set(trace)
        if not common:
            raise ValueError("success traces share no common states")

        first_trace = list(traces[0])
        essential = tuple(state for state in first_trace if state in common)
        return cls(essential)

    def validate(self, trace: Iterable[str | AgenticTraceEvent]) -> AgenticValidationResult:
        observed = tuple(event.state if isinstance(event, AgenticTraceEvent) else str(event) for event in trace)
        matched: list[str] = []
        missing: list[str] = []
        cursor = 0

        for required in self.essential_states:
            try:
                next_index = observed.index(required, cursor)
            except ValueError:
                missing.append(required)
                continue
            matched.append(required)
            cursor = next_index + 1

        out_of_order = self._find_out_of_order(observed)
        return AgenticValidationResult(
            passed=not missing and not out_of_order,
            missing_states=tuple(missing),
            out_of_order_states=tuple(out_of_order),
            matched_states=tuple(matched),
        )

    def _find_out_of_order(self, observed: Sequence[str]) -> list[str]:
        positions: dict[str, int] = {}
        for index, state in enumerate(observed):
            if state in self.essential_states and state not in positions:
                positions[state] = index

        out_of_order: list[str] = []
        last_seen = -1
        for state in self.essential_states:
            if state not in positions:
                continue
            if positions[state] < last_seen:
                out_of_order.append(state)
            last_seen = max(last_seen, positions[state])
        return out_of_order
