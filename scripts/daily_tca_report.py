from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils.performance_analyzer import PerformanceAnalyzer
from utils.presentation_formatters import format_daily_tca_report

logger = logging.getLogger("DailyTCAReportJob")


@dataclass(frozen=True)
class DailyTcaReportConfig:
    metrics_log_path: str
    state_path: str
    send_hour_utc: int = 8
    send_minute_utc: int = 0
    send_window_minutes: int = 5


class DailyTcaReportJob:
    def __init__(self, broadcaster: Any, config: DailyTcaReportConfig) -> None:
        self.broadcaster = broadcaster
        self.config = config

    def should_send(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        now_utc = now.astimezone(timezone.utc)
        if now_utc.hour != self.config.send_hour_utc:
            return False
        if now_utc.minute < self.config.send_minute_utc:
            return False
        if now_utc.minute >= self.config.send_minute_utc + self.config.send_window_minutes:
            return False
        last_sent = self._load_state().get("last_sent_date_utc")
        return last_sent != now_utc.date().isoformat()

    async def run(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        if not self.should_send(now):
            return False

        analyzer = PerformanceAnalyzer(metrics_log_path=self.config.metrics_log_path)
        summary = analyzer.generate_summary()
        if not isinstance(summary, dict) or summary.get("error"):
            logger.info("Daily TCA report skipped: %s", summary.get("error", "invalid summary"))
            return False

        global_summary = summary.get("global", {})
        if int(global_summary.get("total_orders", 0) or 0) <= 0:
            logger.info("Daily TCA report skipped: no executed trades found yet.")
            return False

        message = format_daily_tca_report(
            summary,
            as_of_utc=now.astimezone(timezone.utc),
            metrics_path=self.config.metrics_log_path,
        )
        sent = await self.broadcaster.diffuser_message_au_canal(message)
        if sent:
            self._save_state({"last_sent_date_utc": now.astimezone(timezone.utc).date().isoformat()})
        return sent

    def _load_state(self) -> dict[str, Any]:
        path = Path(self.config.state_path)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Daily TCA state file unreadable, resetting: %s", exc)
            return {}

    def _save_state(self, state: dict[str, Any]) -> None:
        path = Path(self.config.state_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
