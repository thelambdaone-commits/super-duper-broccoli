from datetime import datetime, timezone
from html import escape
from typing import Any, Dict


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


def format_main_menu(is_admin: bool = False):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    keyboard = [
        [
            InlineKeyboardButton("💼 Wallet", callback_data="wallet_refresh"),
            InlineKeyboardButton("📈 Markets", callback_data="help_page_2"),
        ],
        [
            InlineKeyboardButton("⚡ Trading", callback_data="help_page_3"),
        ],
    ]
    if is_admin:
        keyboard[1].append(InlineKeyboardButton("👑 Admin", callback_data="help_page_4"))
    keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data="menu_main")])
    text = "<b>📖 LOBSTAR COMMAND CENTER</b>\n\nChoisis une catégorie :"
    return text, InlineKeyboardMarkup(keyboard)


def _fmt_signal_html(s) -> str:
    fees_str = f" | Fees: {s.fee_rate_bps} bps" if getattr(s, "fee_rate_bps", 0) > 0 else ""
    return (
        f"🏆 <b>{_html(s.reason)}</b>\n"
        f"📡 {_html(s.market_question[:80])}\n"
        f"💰 Vol: <code>${s.volume:,.0f}</code> | Prob: <code>{s.current_prob:.0f}%</code>{fees_str}\n"
        f"📈 Signal: <code>{_html(s.side)} @ {s.price}</code> (conf: <code>{s.confidence:.0%}</code>)\n"
        f"💡 Sentiment: <code>{_html(s.sentiment)}</code>"
    )


def format_scan_report_html(result) -> str:
    sentiment_data = getattr(result, "aggregate_sentiment", {"sentiment": "NEUTRAL", "bullish_pct": 50})
    sent_label = sentiment_data.get("sentiment", "NEUTRAL")
    bull_pct = sentiment_data.get("bullish_pct", 50)

    parts = [
        f"📊 <b>QUANT MARKET SCAN</b> — <code>{result.total_markets_scanned}</code> markets",
        f"🌍 <b>Market Feeling</b>: <code>{sent_label}</code> ({bull_pct:.1f}% bull)\n"
    ]

    if hasattr(result, "winning_bets") and result.winning_bets:
        parts.append("💎 <b>TOP ALPHA OPPORTUNITIES</b>")
        for s in result.winning_bets[:3]:
            parts.append(_fmt_signal_html(s))
            parts.append("")

    if hasattr(result, "trending_markets") and result.trending_markets:
        parts.append("📈 <b>TRENDING VOLATILITY</b>")
        for s in result.trending_markets[:3]:
            parts.append(_fmt_signal_html(s))
            parts.append("")

    if hasattr(result, "arbitrage_opportunities") and result.arbitrage_opportunities:
        parts.append("💰 <b>ARBITRAGE SIGNALS</b>")
        for s in result.arbitrage_opportunities[:3]:
            parts.append(_fmt_signal_html(s))
            parts.append("")

    parts.append(f"\n<i>Generated by Telegram Lobster AI at {datetime.now().strftime('%H:%M:%S')} UTC</i>")
    return "\n".join(parts)


def format_market_report(markets) -> str:
    if not markets:
        return "🔍 <b>Market Discovery</b>\nNo active contracts found."
    parts = ["<b>📡 LIVE MARKET FEED</b>", "───────────────────"]
    for m in markets[:6]:
        try:
            pct = m.probability_pct
            bar = "█" * int(pct / 10) + "░" * (10 - int(pct / 10))
            parts.append(f"• <b>{_html(m.question[:45])}</b>\n  <code>{bar}</code> <code>{pct:.0f}%</code> | <code>${m.yes_price:.3f}</code>")
        except Exception:
            parts.append(f"• {_html(m.question[:45])}")
    parts.append("───────────────────")
    return "\n".join(parts)


def format_winning_bets_alert(signals) -> str:
    if not signals:
        return ""
    parts = ["<b>🏆 SIGNAL ALERT — ALPHA DETECTED</b>", "───────────────────"]
    for s in signals:
        parts.append(
            f"🔹 <b>{_html(s.market_question[:60])}</b>\n"
            f"   Side: <b>{_html(s.side)}</b> | Prob: <code>{s.current_prob:.0f}%</code>\n"
            f"   Conf: <code>{s.confidence:.0%}</code> | Vol: <code>${s.volume:,.0f}</code>"
        )
    parts.append("───────────────────")
    parts.append("⚡ <i>Execution via Institutional Cockpit /p</i>")
    return "\n".join(parts)


def format_unified_feed_report(markets_general: list, intelligence_report) -> str:
    """Format combined general feed and crypto intelligence report."""
    parts = ["<b>📡 LIVE MARKET FEED — TOP ALPHA</b>", "───────────────────"]

    def _days_to_resolution(market: Any) -> float | None:
        end_date = getattr(market, "end_date", "") or ""
        if not end_date:
            return None
        try:
            end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
            return (end_dt - datetime.now(timezone.utc)).total_seconds() / 86400.0
        except Exception:
            return None

    filtered_markets = []
    for market in markets_general:
        question = getattr(market, "question", "") or ""
        slug = getattr(market, "slug", "") or ""
        if question.lower().startswith("dev vs") or slug.lower().startswith("dev-"):
            continue
        days = _days_to_resolution(market)
        if days is not None and days > 3.0:
            continue
        filtered_markets.append(market)

    if not filtered_markets:
        filtered_markets = markets_general[:8]

    for m in filtered_markets[:8]:
        try:
            pct = getattr(m, 'probability_pct', None)
            if pct is None:
                pct = getattr(m, 'yes_price', 0.0) * 100.0

            yes_price = getattr(m, 'yes_price', 0.0)
            question = _html(getattr(m, 'question', 'Unknown Market'))
            days = _days_to_resolution(m)
            horizon = f" | T- <code>{days:.1f}j</code>" if isinstance(days, (int, float)) else ""

            bar = "█" * int(pct / 10) + "░" * (10 - int(pct / 10))
            parts.append(f"• <b>{question[:55]}</b>\n  <code>{bar}</code> <code>{pct:.0f}%</code> | <code>${yes_price:.3f}</code>{horizon}")
        except Exception:
            question = _html(getattr(m, 'question', 'Unknown Market'))
            parts.append(f"• {question[:50]}")

    parts.append("───────────────────")

    # Add a blank line and then the Lobstar Crypto Intelligence section
    from utils.crypto_market_intelligence import format_intelligence_report
    parts.append(format_intelligence_report(intelligence_report))
    return "\n".join(parts)
