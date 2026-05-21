from __future__ import annotations

import logging
from typing import Any

from utils.message_formatter import InstitutionalMessageFormatter

logger = logging.getLogger("PostTradeService")


class PostTradeService:
    def __init__(
        self,
        trade_notifications: Any,
        metrics_exporter: Any,
        notifier: Any,
        listener: Any,
        circuit_breaker: Any,
    ) -> None:
        self.trade_notifications = trade_notifications
        self.metrics_exporter = metrics_exporter
        self.notifier = notifier
        self.listener = listener
        self.circuit_breaker = circuit_breaker

    async def finalize(self, signal: dict, result: dict, execution_mode: str) -> None:
        if result.get("status") == "SUCCESS":
            await self._handle_success(signal, result, execution_mode)
        elif result.get("status") == "SKIPPED":
            logger.info("Signal skipped: %s", result.get("reason", "No reason provided"))
            return
        else:
            await self._handle_failure(signal, result)

        confirmation = InstitutionalMessageFormatter.format_trade_execution_html(result)
        chat_id = signal.get("chat_id")
        update = signal.get("update")
        if update is not None and update.message:
            await self.listener.reply_to(confirmation, update, parse_mode="HTML")
        elif chat_id:
            await self.listener.send_message(confirmation, chat_id=chat_id, parse_mode="HTML")

    async def _handle_success(self, signal: dict, result: dict, execution_mode: str) -> None:
        logger.info(f"Signal executed successfully: {result.get('trade_id', 'N/A')}")
        if self.trade_notifications:
            self.trade_notifications.send_trade_execution(signal, result, execution_mode, success=True)
        else:
            self.notifier.send("Trade Executed")

        if self.metrics_exporter:
            try:
                await self.metrics_exporter.log_execution(signal, result)
            except Exception as exc:
                logger.warning("Failed to export execution metrics: %s", exc)
        self.circuit_breaker.record_success()

    async def _handle_failure(self, signal: dict, result: dict) -> None:
        reason = result.get("reason_1") or result.get("reason") or "Unknown error"
        logger.warning(f"Signal execution failed: {reason}")
        self.notifier.send(
            f"⚠️ *Execution Failed*\nTicker: `{result.get('ticker', 'Unknown')}`\nReason: `{reason}`"
        )
        self.circuit_breaker.record_failure(reason)
