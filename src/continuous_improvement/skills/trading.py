import logging
from typing import Any, Optional

from continuous_improvement.skills.base import Skill

logger = logging.getLogger("CI_Skill_Trading")


class TradingSkill(Skill):
    @property
    def name(self) -> str:
        return "trading"

    @property
    def description(self) -> str:
        return "Analyzes trading logic: signal parsing, sizing, strategy composition"

    @property
    def priority_files(self) -> list[str]:
        return [
            "polymarket/execution/signal_executor.py",
            "services/portfolio_risk_engine.py",
            "utils/signal_parser.py",
            "strategies/arbitrage_scanner.py",
            "strategies/sentiment_nlp.py",
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
                    if "magic" in line.lower() and "number" in line.lower():
                        issues.append({
                            "file": filepath,
                            "line": i,
                            "severity": "info",
                            "message": "Magic number detected, consider extracting as constant",
                            "snippet": line.strip()[:80],
                        })
            except (IOError, FileNotFoundError):
                pass
        return issues

    def suggest_improvements(self, paths: Optional[list[str]] = None) -> list[dict[str, Any]]:
        return [
            {
                "component": "signal_executor",
                "suggestion": "Add confidence threshold as configurable parameter instead of hardcoded 0.5",
                "priority": "medium",
                "impact": "Allows dynamic tuning per market regime",
            },
            {
                "component": "portfolio_risk_engine",
                "suggestion": "Add position reversal detection to avoid flip-flopping on consecutive signals",
                "priority": "high",
                "impact": "Reduces slippage from rapid direction changes",
            },
            {
                "component": "arbitrage_scanner",
                "suggestion": "Add minimum profitability filter that accounts for gas costs on Polygon",
                "priority": "medium",
                "impact": "Prevents unprofitable arbitrage executions",
            },
        ]

    def generate_tests(self, paths: Optional[list[str]] = None) -> list[dict[str, Any]]:
        return [
            {
                "target": "polymarket/execution/signal_executor.py",
                "test_file": "tests/test_signal_executor.py",
                "description": "Integration test: execute_regex_signal with mocked FreqAIEngine and Ledger",
                "test_cases": [
                    "test_regex_signal_buy_executes_correctly",
                    "test_regex_signal_sell_executes_correctly",
                    "test_regex_signal_zero_size_skipped",
                    "test_regex_signal_replay_mode_logs_only",
                    "test_regex_signal_paper_mode_records_position",
                    "test_lobstar_signal_low_confidence_skipped",
                    "test_lobstar_signal_incomplete_decision_skipped",
                    "test_lobstar_signal_nominal_execution",
                ],
            },
        ]
