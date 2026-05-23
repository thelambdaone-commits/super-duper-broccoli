import logging
from typing import Any, Optional

from continuous_improvement.skills.base import Skill

logger = logging.getLogger("CI_Skill_DataIngestion")


class DataIngestionSkill(Skill):
    @property
    def name(self) -> str:
        return "data_ingestion"

    @property
    def description(self) -> str:
        return "Analyzes market data ingestion, normalization, freshness, and source quality"

    @property
    def priority_files(self) -> list[str]:
        return [
            "scrapers/data_pipeline.py",
            "utils/market_data_reader.py",
            "utils/orderbook_scraper.py",
            "scrapers/web_scraper.py",
            "scrapers/clob_listener.py",
        ]

    def detect_issues(self, paths: Optional[list[str]] = None) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        for filepath in (paths or self.priority_files):
            try:
                with open(filepath) as f:
                    content = f.read().lower()
                if "timezone" not in content and "timestamp" in content:
                    issues.append({
                        "file": filepath,
                        "severity": "info",
                        "message": "Timestamp handling present but no explicit timezone normalization found",
                    })
                if "retry" not in content and ("http" in content or "api" in content):
                    issues.append({
                        "file": filepath,
                        "severity": "info",
                        "message": "Remote source handling found without explicit retry/backoff mention",
                    })
            except (IOError, FileNotFoundError):
                pass
        return issues

    def suggest_improvements(self, paths: Optional[list[str]] = None) -> list[dict[str, Any]]:
        return [
            {
                "component": "data_pipeline",
                "suggestion": "Add explicit source freshness and last-updated metadata to every normalized feed",
                "priority": "high",
                "impact": "Prevents stale market data from reaching signal generation",
            },
            {
                "component": "market_data_reader",
                "suggestion": "Standardize timezone handling and monotonic timestamps across all sources",
                "priority": "high",
                "impact": "Reduces ordering bugs and lookback drift",
            },
            {
                "component": "orderbook_scraper",
                "suggestion": "Add structured gap detection for missing books, empty bids, and stale snapshots",
                "priority": "medium",
                "impact": "Improves data quality and downstream risk gating",
            },
        ]

    def generate_tests(self, paths: Optional[list[str]] = None) -> list[dict[str, Any]]:
        return [
            {
                "target": "scrapers/data_pipeline.py",
                "test_file": "tests/test_data_pipeline.py",
                "description": "Validates ingestion normalization, freshness, and fallbacks",
                "test_cases": [
                    "test_pipeline_normalizes_market_payloads",
                    "test_pipeline_marks_stale_sources",
                    "test_pipeline_handles_missing_fields",
                    "test_pipeline_preserves_timezone_awareness",
                ],
            },
        ]
