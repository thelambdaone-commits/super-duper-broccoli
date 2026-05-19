import logging
from datetime import datetime
from html import escape
from typing import Any, Dict, List


def _html(value: Any) -> str:
    return escape(str(value), quote=False)


def _fmt_number(value: Any, precision: int = 2, default: float = 0.0) -> str:
    try:
        return f"{float(value):.{precision}f}"
    except (TypeError, ValueError):
        return f"{default:.{precision}f}"


class InstitutionalMessageFormatter:
    """
    Formats system events into high-fidelity institutional reports.
    Focuses on explainability, data richness, and professional aesthetics.
    """
    
    @staticmethod
    def format_trade_execution(data: Dict[str, Any]) -> str:
        """📈 TRADE EXECUTED Report"""
        return (
            f"📈 *TRADE EXECUTED*\n\n"
            f"Market: `{data.get('ticker', 'UNKNOWN')}`\n"
            f"Direction: *{data.get('side', 'N/A')}*\n"
            f"Sentiment: `{data.get('sentiment', 'NEUTRAL')}`\n"
            f"Probability: `{data.get('probability', 0.0):.2f}`\n"
            f"Kelly Allocation: `{data.get('kelly_pct', 0.0):.1f}%`\n"
            f"Regime: `{data.get('regime', 'STABLE')}`\n"
            f"Execution: `{data.get('path', 'PASSIVE_MAKER')}`\n"
            f"Slippage Est: `{data.get('slippage_bps', 0.0):.2f}bps`\n\n"
            f"*Reasoning:*\n"
            f"• {data.get('reason_1', 'Pattern alignment detected')}\n"
            f"• {data.get('reason_2', 'Liquidity depth sufficient')}\n"
            f"• {data.get('reason_3', 'Risk thresholds validated')}\n\n"
            f"Trade ID: `#{data.get('trade_id', 'N/A')}`"
        )

    @staticmethod
    def format_trade_execution_html(data: Dict[str, Any]) -> str:
        """Telegram-safe HTML trade report."""
        status = str(data.get("status") or data.get("execution_status") or "SUCCESS").upper()
        status_labels = {
            "SUCCESS": "TRADE CONFIRMED",
            "EXECUTED": "TRADE CONFIRMED",
            "FILLED": "TRADE CONFIRMED",
            "FAILED": "TRADE FAILED",
            "ERROR": "TRADE FAILED",
            "REJECTED": "TRADE REJECTED",
            "SKIPPED": "TRADE SKIPPED",
            "PAPER": "PAPER TRADE RECORDED",
            "DRY_RUN": "DRY RUN RECORDED",
        }
        title = status_labels.get(status, "TRADE SIGNAL PROCESSED")
        reasons = [
            data.get("reason_1", "Pattern alignment detected"),
            data.get("reason_2", "Liquidity depth sufficient"),
            data.get("reason_3", "Risk thresholds validated"),
        ]
        reason_lines = "\n".join(f"• {_html(reason)}" for reason in reasons if reason)

        lines = [
            f"<b>{_html(title)}</b>",
            "",
            f"Status: <b>{_html(status)}</b>",
            f"Market: <code>{_html(data.get('ticker', 'UNKNOWN'))}</code>",
            f"Direction: <b>{_html(data.get('side', 'N/A'))}</b>",
            f"Sentiment: <code>{_html(data.get('sentiment', 'NEUTRAL'))}</code>",
            f"Probability: <code>{_fmt_number(data.get('probability'), 2)}</code>",
            f"Kelly Allocation: <code>{_fmt_number(data.get('kelly_pct'), 1)}%</code>",
            f"Regime: <code>{_html(data.get('regime', 'STABLE'))}</code>",
            f"Execution: <code>{_html(data.get('path', 'PASSIVE_MAKER'))}</code>",
            f"Slippage Est: <code>{_fmt_number(data.get('slippage_bps'), 2)}bps</code>",
            "",
            "<b>Reasoning</b>",
            reason_lines,
            "",
            f"Trade ID: <code>#{_html(data.get('trade_id', 'N/A'))}</code>",
        ]
        return "\n".join(lines).strip()

    @staticmethod
    def format_risk_alert(data: Dict[str, Any]) -> str:
        """⚠️ RISK ALERT Report"""
        return (
            f"⚠️ *RISK ALERT*\n\n"
            f"*Threshold Exceeded:* {data.get('metric', 'Portfolio Beta')}\n\n"
            f"*Current Exposures:*\n"
            + "\n".join([f"• {k}: `{v:.2f}`" for k, v in data.get("exposures", {}).items()]) + "\n\n"
            f"*Action Taken:*\n"
            f"• {data.get('action', 'Position sizing reduced for safety')}\n\n"
            f"*Rationale:*\n"
            f"{data.get('rationale', 'Correlated drawdown probability increased.')}"
        )

    @staticmethod
    def format_model_drift(data: Dict[str, Any]) -> str:
        """📉 MODEL DRIFT Report"""
        return (
            f"📉 *MODEL DRIFT DETECTED*\n\n"
            f"Ticker: `{data.get('ticker', 'N/A')}`\n"
            f"PSI Threshold: `{data.get('psi', 0.0):.3f} > 0.2`\n\n"
            f"*Status:* Retraining pipeline triggered autonomously."
        )

    @staticmethod
    def format_market_scan(data: Dict[str, Any]) -> str:
        """📊 Market Intelligence Summary"""
        winners = data.get("winners", [])
        surebets = data.get("surebets", [])
        core_signals = data.get("core_signals", [])
        
        report = f"📊 *QUANT INTELLIGENCE SUMMARY*\n\n"
        
        if core_signals:
            report += "💎 *CORE CRYPTO SIGNALS* (BTC/ETH/SOL)\n"
            for s in core_signals[:3]:
                sentiment_emoji = "📈" if s.get('sentiment') == "BULLISH" else "📉" if s.get('sentiment') == "BEARISH" else "⚖️"
                report += f"• {s['ticker']}: {sentiment_emoji} *{s['side']}* | Prob: {s['prob']:.0f}%\n"
            report += "\n"

        if surebets:
            report += "💰 *ARBITRAGE OPPORTUNITIES*\n"
            for s in surebets[:3]:
                report += f"• {s['ticker']}: Sum={s['sum_price']:.3f} -> *SUREBET*\n"
            report += "\n"
            
        report += f"🔍 *SCAN METRICS*\n"
        report += f"• Markets Analyzed: `{data.get('total', 0)}`\n"
        report += f"• Alpha Signals: `{len(winners)}` (near resolution)\n"
        report += f"• Health: `OPTIMAL`\n\n"
        report += f"_Generated by Telegram Lobster AI_"
        return report

def format_scan_report(result) -> str:
    sentiment_data = getattr(result, "aggregate_sentiment", {"sentiment": "NEUTRAL", "bullish_pct": 50})
    sent_label = sentiment_data.get("sentiment", "NEUTRAL")
    bull_pct = sentiment_data.get("bullish_pct", 50)
    
    parts = [
        f"📊 *QUANT MARKET SCAN* — `{result.total_markets_scanned}` markets",
        f"🌍 *Market Feeling:* `{sent_label}` ({bull_pct:.1f}% bullish)\n"
    ]
    
    from utils.market_scanner import _fmt_signal

    if hasattr(result, 'winning_bets') and result.winning_bets:
        parts.append("💎 *TOP ALPHA OPPORTUNITIES*")
        for s in result.winning_bets[:3]:
            parts.append(_fmt_signal(s))
            parts.append("")

    if hasattr(result, 'trending_markets') and result.trending_markets:
        parts.append("📈 *TRENDING VOLATILITY*")
        for s in result.trending_markets[:3]:
            parts.append(_fmt_signal(s))
            parts.append("")

    if hasattr(result, 'arbitrage_opportunities') and result.arbitrage_opportunities:
        parts.append("💰 *ARBITRAGE SIGNALS*")
        for s in result.arbitrage_opportunities[:3]:
            parts.append(_fmt_signal(s))
            parts.append("")

    parts.append(f"\n_Generated by Telegram Lobster AI at {datetime.now().strftime('%H:%M:%S')} UTC_")
    return "\n".join(parts)


def format_market_report(markets) -> str:
    if not markets:
        return "🔍 *Market Discovery*\nNo active contracts found."
    parts = ["📡 *LIVE MARKET FEED*\n"]
    for m in markets[:8]:
        try:
            pct = m.probability_pct
            bar = "█" * int(pct / 10) + "░" * (10 - int(pct / 10))
            parts.append(f"• *{m.question[:50]}*\n  {bar} `{pct:.0f}%` | `${m.yes_price:.3f}`\n")
        except Exception:
            parts.append(f"• {m.question[:50]}\n")
    return "\n".join(parts)


def format_winning_bets_alert(signals) -> str:
    if not signals:
        return ""
    parts = ["🏆 *INSTITUTIONAL SIGNAL ALERT*"]
    for s in signals:
        parts.append(
            f"\n🔹 *{s.market_question[:60]}*"
            f"\n   Side: `{s.side}` at {s.current_prob:.0f}%"
            f"\n   Conf: `{s.confidence:.0%}` | Vol: `${s.volume:,.0f}`"
            f"\n   Sentiment: *{s.sentiment}* | {s.direction}"
        )
    parts.append("\n⚡ _Execution suggested via /p or direct signal_")
    return "\n".join(parts)


def format_unified_feed_report(markets_general: list, intelligence_report) -> str:
    """Format combined general feed and crypto intelligence report."""
    parts = ["📡 LIVE MARKET FEED\n"]
    for m in markets_general[:8]:
        try:
            # Check if probability_pct or yes_price is present
            pct = getattr(m, 'probability_pct', None)
            if pct is None:
                pct = getattr(m, 'yes_price', 0.0) * 100.0
            
            yes_price = getattr(m, 'yes_price', 0.0)
            question = getattr(m, 'question', 'Unknown Market')
            
            bar = "█" * int(pct / 10) + "░" * (10 - int(pct / 10))
            parts.append(f"  • {question[:50]}\n    {bar} {pct:.0f}% | ${yes_price:.3f}\n")
        except Exception:
            question = getattr(m, 'question', 'Unknown Market')
            parts.append(f"  • {question[:50]}\n")

    # Add a blank line and then the Lobstar Crypto Intelligence section
    from utils.crypto_market_intelligence import format_intelligence_report
    parts.append("\n" + format_intelligence_report(intelligence_report))
    return "\n".join(parts)
