import logging
from typing import Any, Optional

from continuous_improvement.skills.base import Skill

logger = logging.getLogger("CI_Skill_Backtesting")


class BacktestingSkill(Skill):
    @property
    def name(self) -> str:
        return "backtesting"

    @property
    def description(self) -> str:
        return "Analyzes simulation, walk-forward validation, scenario replay, and backtest integrity"

    @property
    def priority_files(self) -> list[str]:
        return [
            "scripts/backtest_simulation.py",
            "scripts/simulate_trades.py",
            "core/training_pipeline.py",
            "core/performance_attribution.py",
            "continuous_improvement/agents/forensic_postmortem.py",
        ]

    def detect_issues(self, paths: Optional[list[str]] = None) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        for filepath in (paths or self.priority_files):
            try:
                with open(filepath) as f:
                    content = f.read().lower()
                if "train_test_split" in content:
                    issues.append({
                        "file": filepath,
                        "severity": "high",
                        "message": "Potential lookahead risk in time-series validation",
                    })
                if "slippage" not in content and ("backtest" in filepath or "simulate" in filepath):
                    issues.append({
                        "file": filepath,
                        "severity": "info",
                        "message": "Backtest path found without explicit slippage/cost modeling mention",
                    })
            except (IOError, FileNotFoundError):
                pass
        return issues

    def suggest_improvements(self, paths: Optional[list[str]] = None) -> list[dict[str, Any]]:
        return [
            {
                "component": "backtest_simulation",
                "suggestion": "Add walk-forward and regime-aware evaluation splits",
                "priority": "high",
                "impact": "Reduces leakage and gives a more realistic estimate of live performance",
            },
            {
                "component": "simulate_trades",
                "suggestion": "Include fees, spread, slippage, and latency in every replay path",
                "priority": "high",
                "impact": "Aligns simulated outcomes with execution reality",
            },
            {
                "component": "performance_attribution",
                "suggestion": "Break attribution into model alpha, execution alpha, and regime alpha",
                "priority": "medium",
                "impact": "Improves debugging of performance changes",
            },
        ]

    def generate_tests(self, paths: Optional[list[str]] = None) -> list[dict[str, Any]]:
        return [
            {
                "target": "scripts/backtest_simulation.py",
                "test_file": "tests/test_pnl_pipeline.py",
                "description": "Validates simulation contract, costs, and attribution alignment",
                "test_cases": [
                    "test_backtest_applies_fees_and_slippage",
                    "test_backtest_respects_execution_mode",
                    "test_backtest_records_reconciliation_metrics",
                    "test_backtest_uses_regime_filters",
                ],
            },
        ]
