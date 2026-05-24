from __future__ import annotations

from enum import StrEnum


class ExecutionMode(StrEnum):
    REPLAY = "REPLAY"
    PAPER = "PAPER"
    SHADOW = "SHADOW"
    PROD = "PROD"


EXECUTION_MODE_VALUES = {mode.value for mode in ExecutionMode}


def normalize_execution_mode(mode: str | ExecutionMode | None, default: ExecutionMode = ExecutionMode.PAPER) -> ExecutionMode:
    if mode is None:
        return default
    if isinstance(mode, ExecutionMode):
        return mode
    normalized = str(mode).upper().strip()
    try:
        return ExecutionMode(normalized)
    except ValueError as exc:
        raise ValueError(f"Invalid execution mode: {mode}. Choose from {sorted(EXECUTION_MODE_VALUES)}") from exc

