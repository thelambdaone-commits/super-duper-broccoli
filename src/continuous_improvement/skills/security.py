import logging
from typing import Any, Optional

from continuous_improvement.skills.base import Skill

logger = logging.getLogger("CI_Skill_Security")

SECRET_PATTERNS = [
    "api_key",
    "api_secret",
    "api_passphrase",
    "private_key",
    "bot_token",
    "password",
    "secret",
    "token",
]


class SecuritySkill(Skill):
    @property
    def name(self) -> str:
        return "security"

    @property
    def description(self) -> str:
        return "Analyzes secret exposure, vault usage, input validation, and access control"

    @property
    def priority_files(self) -> list[str]:
        return [
            "utils/vault_handler.py",
            "polymarket/execution/freqai_engine.py",
            "api/api_server.py",
            "mcp_agents/mcp_server.py",
            "scrappers/mets_telegram_scraper.py",
        ]

    def detect_issues(self, paths: Optional[list[str]] = None) -> list[dict[str, Any]]:
        issues = []
        target_paths = paths or self.priority_files
        for filepath in target_paths:
            try:
                with open(filepath) as f:
                    content = f.read()
                for i, line in enumerate(content.split("\n"), 1):
                    lower = line.lower().strip()
                    for pat in SECRET_PATTERNS:
                        if pat in lower and "=" in lower and not lower.strip().startswith("#"):
                            if "os.getenv" not in lower and "secrets[" not in lower and "vault" not in lower:
                                issues.append({
                                    "file": filepath,
                                    "line": i,
                                    "severity": "high",
                                    "message": f"Potential secret exposure: '{pat}' on line {i}",
                                    "snippet": line.strip()[:80],
                                })
            except (IOError, FileNotFoundError):
                issues.append({"file": filepath, "severity": "info", "message": "File not found, skipping"})
        return issues

    def suggest_improvements(self, paths: Optional[list[str]] = None) -> list[dict[str, Any]]:
        return [
            {
                "component": "vault_handler",
                "suggestion": "Add vault token rotation and auto-renewal before expiry",
                "priority": "high",
                "impact": "Prevents auth failures during long-running sessions",
            },
            {
                "component": "api_server",
                "suggestion": "Add rate limiting and API key authentication to FastAPI endpoints",
                "priority": "medium",
                "impact": "Prevents unauthorized access to trading endpoints",
            },
            {
                "component": "telegram_listener",
                "suggestion": "Validate that incoming chat_id matches expected channel before processing",
                "priority": "high",
                "impact": "Prevents signal injection from unauthorized chats",
            },
        ]
