import logging
from typing import Any, Optional

from continuous_improvement.skills.base import Skill

logger = logging.getLogger("CI_Skill_Execution")


class ExecutionSkill(Skill):
    @property
    def name(self) -> str:
        return "execution"

    @property
    def description(self) -> str:
        return "Analyzes CLOB execution logic: maker/taker, order lifecycle, fallback paths"

    @property
    def priority_files(self) -> list[str]:
        return [
            "execution/passive_executor.py",
            "polymarket/execution/freqai_engine.py",
            "polymarket/execution/signal_executor.py",
        ]

    def detect_issues(self, paths: Optional[list[str]] = None) -> list[dict[str, Any]]:
        issues = []
        target_paths = paths or self.priority_files
        for filepath in target_paths:
            try:
                with open(filepath) as f:
                    content = f.read()
                lines = content.split("\n")
                for i, line in enumerate(lines, 1):
                    if "except Exception" in line and "pass" in line:
                        issues.append({
                            "file": filepath,
                            "line": i,
                            "severity": "medium",
                            "message": "Bare except Exception with pass — hides execution failures",
                            "snippet": line.strip()[:80],
                        })
            except (IOError, FileNotFoundError):
                pass
        return issues

    def suggest_improvements(self, paths: Optional[list[str]] = None) -> list[dict[str, Any]]:
        return [
            {
                "component": "passive_executor",
                "suggestion": "Add exponential backoff for taker retries on transient failures",
                "priority": "medium",
                "impact": "Increases fill rate during network congestion",
            },
            {
                "component": "freqai_engine",
                "suggestion": "Add circuit breaker for repeated CLOB connection failures (N failures in M minutes)",
                "priority": "high",
                "impact": "Prevents cascading errors when CLOB is degraded",
            },
            {
                "component": "signal_executor",
                "suggestion": "Log fill price vs signal price to track slippage in PROD mode",
                "priority": "medium",
                "impact": "Enables slippage analysis and execution quality monitoring",
            },
        ]

    def generate_tests(self, paths: Optional[list[str]] = None) -> list[dict[str, Any]]:
        return [
            {
                "target": "execution/passive_executor.py",
                "test_file": "tests/test_passive_executor.py",
                "description": "Additional edge cases for PassiveExecutor",
                "test_cases": [
                    "test_maker_timeout_calibrator_reduces_timeout_on_erratic_regime",
                    "test_maker_timeout_calibrator_fallback_on_exception",
                    "test_concurrent_orders_maintain_separate_queues",
                ],
            },
        ]
