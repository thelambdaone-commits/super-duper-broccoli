from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("ExecutionMetricsExporter")


class ExecutionMetricsExporter:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        config = config or {}
        self.config = config
        self.output_path = str(config.get("metrics_log_path", "data/execution_metrics.jsonl"))
        self._lock = asyncio.Lock()

    async def log_execution(self, signal: Any, report: dict[str, Any]) -> None:
        try:
            payload = self._build_payload(signal, report)
            await asyncio.to_thread(self._append_to_file, payload)
        except Exception as exc:
            logger.error("Friction Metrics: unable to export execution report: %s", exc)

    def _build_payload(self, signal: Any, report: dict[str, Any]) -> dict[str, Any]:
        requested_qty = self._coerce_float(
            report.get("requested_qty", self._signal_value(signal, "requested_qty", "size", "size_usd", default=0.0))
        )
        filled_qty = self._coerce_float(
            report.get("filled_qty", report.get("executed_size", report.get("total_filled_qty", 0.0)))
        )
        execution_price = self._coerce_float(
            report.get("execution_price", report.get("filled_price", report.get("target_price", report.get("price", 0.0))))
        )
        notional_usd = self._coerce_float(
            report.get("notional_usd", filled_qty * execution_price)
        )
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "asset": self._signal_value(signal, "asset", "ticker", "token_id"),
            "direction": self._signal_value(signal, "direction", "side", "action"),
            "size_usd": float(self._signal_value(signal, "size_usd", "size", "allocated_capital", default=0.0) or 0.0),
            "strategy": report.get("strategy", "IMMEDIATE"),
            "status": report.get("status", "UNKNOWN"),
            "ticker": report.get("ticker", self._signal_value(signal, "ticker", "asset", "token_id")),
            "target_price": float(report.get("target_price", report.get("price", 0.0)) or 0.0),
            "requested_qty": requested_qty,
            "filled_qty": filled_qty,
            "execution_price": execution_price,
            "notional_usd": notional_usd,
            "executed_size_usd": float(report.get("executed_size", report.get("total_filled_usd", notional_usd)) or 0.0),
            "slices_filled": int(report.get("slices_filled", 0) or 0),
            "slices_attempted": int(report.get("slices_attempted", 0) or 0),
            "realized_participation_rate": float(report.get("realized_participation_rate", 0.0) or 0.0),
            "avg_market_volume_observed": float(report.get("avg_market_volume_observed", 0.0) or 0.0),
            "volume_capped_events": int(report.get("volume_capped_events", 0) or 0),
            "total_filled_usd": float(report.get("total_filled_usd", 0.0) or 0.0),
            "execution_path": report.get("execution_path", "immediate"),
            "trade_id": report.get("trade_id", ""),
            "reason": report.get("reason_1") or report.get("reason") or "",
        }

    def _append_to_file(self, payload: dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(self.output_path), exist_ok=True)
        line = json.dumps(payload, sort_keys=True, default=str) + "\n"
        with open(self.output_path, "a", encoding="utf-8") as handle:
            handle.write(line)

    @staticmethod
    def _signal_value(signal: Any, *keys: str, default: Any = "") -> Any:
        for key in keys:
            if isinstance(signal, dict) and signal.get(key) is not None:
                return signal.get(key)
            if hasattr(signal, key):
                value = getattr(signal, key)
                if value is not None:
                    return value
        return default

    @staticmethod
    def _coerce_float(value: Any) -> float:
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0
