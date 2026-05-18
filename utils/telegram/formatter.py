from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping


@dataclass(frozen=True)
class TelegramMessageFormatter:
    """Pure formatting utilities for Telegram MarkdownV2 messages."""

    @staticmethod
    def escape_markdown_v2(text: Any) -> str:
        if text is None:
            return ""
        escape_chars = r"_*[]()~`>#+-=|{}.!\\"
        return re.sub(f"([{re.escape(escape_chars)}])", r"\\\1", str(text))

    def format_signal(self, signal: Mapping[str, Any]) -> str:
        ticker = self.escape_markdown_v2(signal.get("ticker", "N/A"))
        regime = self.escape_markdown_v2(signal.get("regime", "N/A"))
        action = self.escape_markdown_v2(
            "YES (BUY)" if str(signal.get("side", "")).upper() in {"BUY", "YES"} else "NO (SELL)"
        )
        p_market = float(signal.get("p_market", 0.0))
        p_real = float(signal.get("p_real", 0.0))
        edge = float(signal.get("edge", 0.0))
        kelly = float(signal.get("kelly", 0.0))
        generated_at = self.escape_markdown_v2(signal.get("timestamp") or datetime.now().strftime("%H:%M:%S UTC"))

        return (
            "🚨 *LOBSTAR QUANT SIGNAL DETECTED*\n"
            "────────────────────────\n"
            f"• *Asset* : `{ticker}`\n"
            f"• *Direction* : *{action}*\n"
            f"• *Market Regime* : `{regime}`\n"
            "────────────────────────\n"
            "📊 *PROBABILISTIC ANALYSIS*:\n"
            f"• `Market Implied Prob : {p_market:.1%}`\n"
            f"• `Calibrated AI Prob  : {p_real:.1%}`\n"
            f"• `Absolute Alpha Edge : {edge:+.1%}`\n"
            "────────────────────────\n"
            "🛡️ *RISK & ALLOCATION*:\n"
            f"• `Target Size (Kelly) : {kelly:.2%}`\n"
            "• `Friction Buffer     : $0.005 / contract`\n"
            "────────────────────────\n"
            f"⏱️ _Generated at: {generated_at}_"
        )

    def format_risk_alert(self, alert: Mapping[str, Any]) -> str:
        severity = str(alert.get("severity", "info")).upper()
        emoji = "⚠️" if severity == "WARNING" else "🔴" if severity == "CRITICAL" else "ℹ️"
        title = self.escape_markdown_v2(alert.get("title", "Alert"))
        body = self.escape_markdown_v2(alert.get("message", ""))
        generated_at = self.escape_markdown_v2(alert.get("timestamp") or datetime.now().strftime("%H:%M:%S UTC"))

        return (
            f"{emoji} *LOBSTAR RISK ALERT*\n"
            "────────────────────────\n"
            f"*{title}*\n"
            f"{body}\n"
            "────────────────────────\n"
            f"⏱️ _At: {generated_at}_"
        )
