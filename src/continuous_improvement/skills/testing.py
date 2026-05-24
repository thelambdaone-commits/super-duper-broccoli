import logging
import os
from typing import Any, Optional

from continuous_improvement.skills.base import Skill

logger = logging.getLogger("CI_Skill_Testing")


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
SOURCE_DIRS = [
    "api",
    "continuous_improvement",
    "core",
    "execution",
    "ledger",
    "mcp_agents",
    "models",
    "monitors",
    "scrapers",
    "scrappers",
    "user_data/freqaimodels",
    "strategies",
    "utils",
]
TEST_DIR = os.path.join(PROJECT_ROOT, "tests")


class TestingSkill(Skill):
    @property
    def name(self) -> str:
        return "testing"

    @property
    def description(self) -> str:
        return "Analyzes test coverage, detects untested modules, suggests test improvements"

    @property
    def priority_files(self) -> list[str]:
        return ["tests/"]

    def detect_issues(self, paths: Optional[list[str]] = None) -> list[dict[str, Any]]:
        issues = []
        tested_modules = set()
        if os.path.exists(TEST_DIR):
            for f in os.listdir(TEST_DIR):
                if f.startswith("test_") and f.endswith(".py"):
                    tested_modules.add(f.replace("test_", "").replace(".py", ""))

        for source_dir in SOURCE_DIRS:
            full_path = os.path.join(PROJECT_ROOT, source_dir)
            if not os.path.exists(full_path):
                continue
            for f in os.listdir(full_path):
                if f.endswith(".py") and not f.startswith("_"):
                    module_name = f.replace(".py", "")
                    expected_test = f"test_{module_name}"
                    if expected_test not in tested_modules and not module_name.startswith("test_"):
                        issues.append({
                            "severity": "high",
                            "message": f"No test file for module '{source_dir}/{module_name}'",
                            "suggestion": f"Create tests/test_{module_name}.py",
                        })
        return issues

    def suggest_improvements(self, paths: Optional[list[str]] = None) -> list[dict[str, Any]]:
        return [
            {
                "component": "tests",
                "suggestion": "Add end-to-end integration test: Telegram → SignalParser → SignalExecutor → Ledger",
                "priority": "high",
                "impact": "Validates the full signal flow in one test",
            },
            {
                "component": "tests",
                "suggestion": "Add performance benchmark tests for FeatureStore queries with 10K+ rows",
                "priority": "medium",
                "impact": "Catches query performance regressions early",
            },
            {
                "component": "tests",
                "suggestion": "Add property-based tests (Hypothesis) for portfolio_risk_engine invariants",
                "priority": "medium",
                "impact": "Discovers edge cases missed by example-based tests",
            },
            {
                "component": "tests",
                "suggestion": "Add a test that verifies all JSON-exportable MCP tool results are serializable",
                "priority": "low",
                "impact": "Prevents runtime serialization errors in MCP responses",
            },
        ]

    def generate_tests(self, paths: Optional[list[str]] = None) -> list[dict[str, Any]]:
        return [
            {
                "target": "all",
                "test_file": "N/A",
                "description": "Test files needed for untested modules",
                "test_cases": [
                    "tests/test_signal_executor.py",
                    "tests/test_mcp_server.py",
                    "tests/test_api_server.py",
                    "tests/test_lobstar_agent.py",
                    "tests/test_vault_handler.py",
                    "tests/test_signal_parser.py",
                ],
            },
        ]
