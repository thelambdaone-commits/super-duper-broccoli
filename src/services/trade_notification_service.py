from __future__ import annotations

import os
from typing import Any, Optional

from utils.presentation_formatters import format_execution_notification


class TradeNotificationService:
    """
    Centralized trade notification boundary.

    This keeps trade execution, Telegram transport, and chat routing separated
    from the orchestrator and execution engine.
    """

    def __init__(self, notifier: Any, fallback_chat_id_env: str = "CHAT_ID") -> None:
        self.notifier = notifier
        self.fallback_chat_id_env = fallback_chat_id_env

    def trade_chat_id(self, signal: dict[str, Any]) -> Optional[str]:
        chat_id = signal.get("trade_chat_id") or signal.get("chat_id")
        if chat_id:
            return str(chat_id)
        env_chat_id = os.getenv("TRADE_ALERT_CHAT_ID") or os.getenv(self.fallback_chat_id_env)
        return str(env_chat_id) if env_chat_id else None

    def send_trade_execution(self, signal: dict[str, Any], result: dict[str, Any], execution_mode: str, success: bool = True) -> bool:
        if not self.notifier:
            return False
        message = format_execution_notification(signal, result, execution_mode, success=success)
        return bool(self.notifier.send(message))

