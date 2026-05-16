import logging
from typing import Any, Optional

from continuous_improvement.skills.base import Skill

logger = logging.getLogger("CI_Skill_Monitoring")


class MonitoringSkill(Skill):
    @property
    def name(self) -> str:
        return "monitoring"

    @property
    def description(self) -> str:
        return "Analyzes logging, metrics, alerting, and observability"

    @property
    def priority_files(self) -> list[str]:
        return [
            "core/signal_executor.py",
            "execution/passive_executor.py",
            "utils/feature_store.py",
            "dashboard.py",
            "api_server.py",
        ]

    def detect_issues(self, paths: Optional[list[str]] = None) -> list[dict[str, Any]]:
        issues = []
        target_paths = paths or self.priority_files
        for filepath in target_paths:
            try:
                with open(filepath) as f:
                    content = f.read()
                if "logging" not in content and "logger" not in content:
                    issues.append({
                        "file": filepath,
                        "severity": "medium",
                        "message": "No logging found — errors will be invisible in production",
                    })
            except (IOError, FileNotFoundError):
                pass
        return issues

    def suggest_improvements(self, paths: Optional[list[str]] = None) -> list[dict[str, Any]]:
        return [
            {
                "component": "all",
                "suggestion": "Add structured logging (JSON format) for log aggregation in production",
                "priority": "medium",
                "impact": "Enables log parsing by tools like Loki, ELK, or Datadog",
            },
            {
                "component": "passive_executor",
                "suggestion": "Export Prometheus-style metrics for fill rate, latency, and fallback counts",
                "priority": "high",
                "impact": "Real-time execution quality monitoring",
            },
            {
                "component": "signal_executor",
                "suggestion": "Alert when consecutive orders fail or circuit breaker trips",
                "priority": "high",
                "impact": "Faster incident response",
            },
            {
                "component": "feature_store",
                "suggestion": "Add a /health endpoint that checks DuckDB connection freshness",
                "priority": "medium",
                "impact": "Prevents silent data pipeline failures",
            },
            {
                "component": "all",
                "suggestion": "Add Sentry or similar error tracking for unhandled exceptions",
                "priority": "medium",
                "impact": "Automatic error reporting with stack traces",
            },
        ]
