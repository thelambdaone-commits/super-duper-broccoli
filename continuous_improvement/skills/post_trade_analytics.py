import logging
from typing import Any, Optional

from continuous_improvement.skills.base import Skill

logger = logging.getLogger("CI_Skill_PostTradeAnalytics")


class PostTradeAnalyticsSkill(Skill):
    @property
    def name(self) -> str:
        return "post_trade_analytics"

    @property
    def description(self) -> str:
        return "Analyzes closed trades, execution quality, attribution, and reconciliation"

    @property
    def priority_files(self) -> list[str]:
        return [
            "core/performance_attribution.py",
            "continuous_improvement/agents/forensic_postmortem.py",
            "ledger/ledger_db.py",
            "execution/passive_executor.py",
            "utils/message_formatter.py",
        ]

    def detect_issues(self, paths: Optional[list[str]] = None) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        for filepath in (paths or self.priority_files):
            try:
                with open(filepath) as f:
                    content = f.read().lower()
                if "pnl" in content and "slippage" not in content:
                    issues.append({
                        "file": filepath,
                        "severity": "info",
                        "message": "PnL logic present but execution slippage attribution not obvious",
                    })
                if "tradeanalysis" not in content and "forensic" in filepath:
                    issues.append({
                        "file": filepath,
                        "severity": "info",
                        "message": "Forensic postmortem path found without explicit analysis object naming",
                    })
            except (IOError, FileNotFoundError):
                pass
        return issues

    def suggest_improvements(self, paths: Optional[list[str]] = None) -> list[dict[str, Any]]:
        return [
            {
                "component": "performance_attribution",
                "suggestion": "Split PnL attribution into selection, timing, and execution components",
                "priority": "high",
                "impact": "Pinpoints whether edge comes from alpha or fill quality",
            },
            {
                "component": "ledger",
                "suggestion": "Add reconciliation reports between paper and live fills",
                "priority": "high",
                "impact": "Prevents silent drift between simulation and production state",
            },
            {
                "component": "forensic_postmortem",
                "suggestion": "Persist post-trade summaries as compact memory entries for later analysis",
                "priority": "medium",
                "impact": "Improves longitudinal learning from closed trades",
            },
        ]

    def generate_tests(self, paths: Optional[list[str]] = None) -> list[dict[str, Any]]:
        return [
            {
                "target": "core/performance_attribution.py",
                "test_file": "tests/test_pnl_pipeline.py",
                "description": "Validates post-trade attribution and reconciliation metrics",
                "test_cases": [
                    "test_attribution_breaks_out_execution_loss",
                    "test_reconciliation_flags_fill_mismatch",
                    "test_closed_trade_summary_updates_memory",
                    "test_slippage_report_is_compact",
                ],
            },
        ]
