from enum import Enum


class ExecutionMode(Enum):
    """Modes d'exécution avec transition contrôlée."""
    PAPER = "PAPER"
    SHADOW = "SHADOW"
    PROD = "PROD"
    PAUSED = "PAUSED"


class SwarmState(Enum):
    """État global de l'essaim."""
    INITIALIZING = "INITIALIZING"
    HEALTHY = "HEALTHY"
    DRIFTING = "DRIFTING"
    CRITICAL = "CRITICAL"
    DEGRADED = "DEGRADED"


class TriggerReason(Enum):
    """Raisons de déclenchement du circuit breaker."""
    NONE = "NONE"
    BRIER_EXCEEDED = "BRIER_EXCEEDED"
    LEGGING_RISK = "LEGGING_RISK"
    DATA_GAP_CRITICAL = "DATA_GAP_CRITICAL"
    PAPER_TICKS_INSUFFICIENT = "PAPER_TICKS_INSUFFICIENT"
