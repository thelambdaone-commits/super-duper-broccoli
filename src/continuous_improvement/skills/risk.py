import logging
from typing import Any, Optional

from continuous_improvement.skills.base import Skill

logger = logging.getLogger("CI_Skill_Risk")


class RiskSkill(Skill):
    @property
    def name(self) -> str:
        return "risk"

    @property
    def description(self) -> str:
        return "Analyzes risk controls: position sizing, circuit breakers, exposure limits, drawdown protection"

    @property
    def priority_files(self) -> list[str]:
        return [
            "services/portfolio_risk_engine.py",
            "ledger/ledger_db.py",
            "mcp_agents/mcp_server.py",
        ]

    def detect_issues(self, paths: Optional[list[str]] = None) -> list[dict[str, Any]]:
        issues = []
        target_paths = paths or self.priority_files
        for filepath in target_paths:
            try:
                with open(filepath) as f:
                    content = f.read()
                if "circuit_breaker" in content.lower() and "max_drawdown" not in content.lower():
                    issues.append({
                        "file": filepath,
                        "severity": "info",
                        "message": "Circuit breaker present but no max drawdown limit detected",
                    })
            except (IOError, FileNotFoundError):
                pass
        return issues

    def suggest_improvements(self, paths: Optional[list[str]] = None) -> list[dict[str, Any]]:
        return [
            {
                "component": "portfolio_risk_engine",
                "suggestion": "Add trailing drawdown-based circuit breaker that auto-engages on N% PnL loss",
                "priority": "high",
                "impact": "Automatic trading halt during sustained losses",
            },
            {
                "component": "ledger",
                "suggestion": "Add daily loss limit that resets at midnight UTC",
                "priority": "high",
                "impact": "Prevents runaway losses within a single trading day",
            },
            {
                "component": "portfolio_risk_engine",
                "suggestion": "Add correlation matrix update mechanism (currently static beta dict)",
                "priority": "medium",
                "impact": "More accurate net beta exposure calculation",
            },
            {
                "component": "mcp_server",
                "suggestion": "Log circuit breaker state changes with reason and actor identity",
                "priority": "medium",
                "impact": "Audit trail for compliance",
            },
            {
                "component": "portfolio_risk_engine",
                "suggestion": "Add sector/asset-class concentration limits beyond single-ticker caps",
                "priority": "medium",
                "impact": "Prevents correlated basket risk",
            },
        ]
