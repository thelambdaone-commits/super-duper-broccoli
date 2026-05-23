from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping
from html import escape

@dataclass(frozen=True)
class TelegramMessageFormatter:
    """Pure formatting utilities for Telegram HTML messages."""

    @staticmethod
    def _html(text: Any) -> str:
        return escape(str(text), quote=False)

    @staticmethod
    def escape_markdown_v2(text: str) -> str:
        """Backward compatibility for MarkdownV2 escaping."""
        from telegram.helpers import escape_markdown
        return escape_markdown(text, version=2)

    def format_signal_html(self, signal: Mapping[str, Any]) -> str:
        ticker = self._html(signal.get("ticker", "N/A"))
        regime = self._html(signal.get("regime", "N/A"))
        action = "<b>YES</b>" if str(signal.get("side", "")).upper() in {"BUY", "YES"} else "<b>NO</b>"
        p_market = float(signal.get("p_market", 0.0))
        p_real = float(signal.get("p_real", 0.0))
        edge = float(signal.get("edge", 0.0))
        kelly = float(signal.get("kelly", 0.0))

        return (
            "<b>🚨 QUANT SIGNAL DETECTED</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"Asset: <code>{ticker}</code>\n"
            f"Action: {action}\n"
            "───────────────────\n"
            "<b>Probabilistic Edge</b>\n"
            f"• Market: <code>{p_market:.1%}</code>\n"
            f"• AI Prob: <code>{p_real:.1%}</code>\n"
            f"• Alpha: <b>{edge:+.1%}</b>\n"
            "───────────────────\n"
            f"<b>Risk:</b> Kelly Size <code>{kelly:.1%}</code>\n"
            f"<b>Regime:</b> <code>{regime}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )

    def format_risk_alert_html(self, alert: Mapping[str, Any]) -> str:
        severity = str(alert.get("severity", "info")).upper()
        emoji = "⚠️" if severity == "WARNING" else "🔴" if severity == "CRITICAL" else "ℹ️"
        title = self._html(alert.get("title", "Alert"))
        body = self._html(alert.get("message", ""))

        return (
            f"<b>{emoji} RISK ALERT: {title}</b>\n"
            "───────────────────\n"
            f"{body}\n"
            "───────────────────"
        )

    def format_signal(self, signal: Mapping[str, Any]) -> str:
        """MarkdownV2 legacy alias, now uses HTML."""
        return self.format_signal_html(signal)

    def format_risk_alert(self, alert: Mapping[str, Any]) -> str:
        """MarkdownV2 legacy alias, now uses HTML."""
        return self.format_risk_alert_html(alert)
