import logging
from typing import Any, Optional

from continuous_improvement.skills.base import Skill

logger = logging.getLogger("CI_Skill_API")


class APISkill(Skill):
    @property
    def name(self) -> str:
        return "api"

    @property
    def description(self) -> str:
        return "Analyzes REST API design, endpoint structure, error handling, and documentation"

    @property
    def priority_files(self) -> list[str]:
        return [
            "api_server.py",
            "dashboard.py",
        ]

    def detect_issues(self, paths: Optional[list[str]] = None) -> list[dict[str, Any]]:
        issues = []
        target_paths = paths or self.priority_files
        for filepath in target_paths:
            try:
                with open(filepath) as f:
                    content = f.read()
                if "raise HTTPException(503" in content:
                    issues.append({
                        "file": filepath,
                        "severity": "info",
                        "message": "Returns 503 on uninitialized components — consider /health endpoint for readiness",
                        "snippet": "503 Service Unavailable on endpoint call",
                    })
            except (IOError, FileNotFoundError):
                pass
        return issues

    def suggest_improvements(self, paths: Optional[list[str]] = None) -> list[dict[str, Any]]:
        return [
            {
                "component": "api_server",
                "suggestion": "Add OpenAPI tags and summary descriptions to all endpoints for better docs",
                "priority": "low",
                "impact": "Auto-generated Swagger UI becomes more usable",
            },
            {
                "component": "api_server",
                "suggestion": "Add PATCH /v1/execution-mode endpoint for partial mode updates",
                "priority": "low",
                "impact": "Consistent RESTful design",
            },
            {
                "component": "api_server",
                "suggestion": "Add GET /v1/features/{ticker} to list available feature names",
                "priority": "medium",
                "impact": "Discoverability of available data",
            },
            {
                "component": "api_server",
                "suggestion": "Add streaming endpoint for live signal feed (SSE or WebSocket)",
                "priority": "medium",
                "impact": "Real-time dashboard updates without polling",
            },
            {
                "component": "dashboard",
                "suggestion": "Add refresh button and auto-refresh toggle for all metrics",
                "priority": "low",
                "impact": "Better UX for live monitoring",
            },
        ]

    def generate_tests(self, paths: Optional[list[str]] = None) -> list[dict[str, Any]]:
        return [
            {
                "target": "api_server.py",
                "test_file": "tests/test_api_server.py",
                "description": "Integration tests for FastAPI endpoints using TestClient",
                "test_cases": [
                    "test_health_returns_ok",
                    "test_v1_ledger_returns_503_when_not_initialized",
                    "test_v1_regime_returns_regime_label",
                    "test_v1_circuit_breaker_engage",
                    "test_v1_circuit_breaker_disengage",
                    "test_v1_execution_mode_get_and_set",
                    "test_v1_sentiment_analyzes_text",
                    "test_v1_sentiment_batch_analyzes_multiple",
                    "test_v1_feature_store_returns_stats",
                ],
            },
        ]
