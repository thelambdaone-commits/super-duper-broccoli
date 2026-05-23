"""Plain text and HTML formatters for trader discovery output."""

from datetime import datetime, timezone
from typing import Optional

from utils.telegram.layout import wallet_url_short
from utils.polymarket_crawler.traders import MarketInfo, EnrichedTrader


def wallet_url(wallet: str) -> str:
    return f"https://polymarket.com/profile/{wallet}"


def fmt_pnl(pnl: float) -> str:
    return f"+${pnl:,.2f}" if pnl >= 0 else f"-${abs(pnl):,.2f}"


def fmt_market_stats(market: MarketInfo) -> str:
    vol = f"${market.volume:,.0f}" if market.volume else "N/A"
    liq = f"${market.liquidity:,.0f}" if market.liquidity else "N/A"
    outcomes_summary = " / ".join(
        f"{o.get('outcome', '?')}: {o.get('price', '?')}" for o in market.outcomes
    )
    return (
        f"  Market: {market.question}\n"
        f"  Vol: {vol} | Liq: {liq} | End: {market.end_date[:10]}\n"
        f"  Outcomes: {outcomes_summary}"
    )


def fmt_trader_alert(trader: EnrichedTrader, market: Optional[MarketInfo] = None) -> str:
    lines = [
        "=" * 56,
        "  TOP TRADER ALERT",
        "=" * 56,
        "",
        f"  Trader: {trader.name} (Rank #{trader.rank} - {trader.category})",
        f"  PnL: {fmt_pnl(trader.total_pnl)} | Volume: ${trader.total_volume:,.0f}",
        f"  Profile: {wallet_url(trader.wallet)}",
        "",
    ]
    if market:
        lines.append(fmt_market_stats(market))
        lines.append("")
    if trader.positions:
        yes_pnl = sum(p.realized_pnl for p in trader.positions if p.side.upper() == "YES")
        no_pnl = sum(p.realized_pnl for p in trader.positions if p.side.upper() == "NO")
        lines.append(f"  Position PnL: YES {fmt_pnl(yes_pnl)} | NO {fmt_pnl(no_pnl)} | Total {fmt_pnl(yes_pnl + no_pnl)}")
        lines.append("")
    if trader.top_markets:
        lines.append(f"  Top Markets ({len(trader.top_markets)}):")
        for slug in trader.top_markets[:5]:
            lines.append(f"    - https://polymarket.com/event/{slug}")
        lines.append("")
    lines.append("-" * 56)
    return "\n".join(lines)


def fmt_expert_leaderboard(traders: list[EnrichedTrader], category: str = "OVERALL", limit: int = 10) -> str:
    lines = [
        f"  Expert Leaderboard — {category}",
        "  " + "-" * 40,
    ]
    for i, t in enumerate(traders[:limit], 1):
        pnl_str = fmt_pnl(t.total_pnl)
        pos_count = len(t.positions)
        lines.append(f"  {i}. {t.name} — PnL: {pnl_str} | Vol: ${t.total_volume:,.0f} | Positions: {pos_count}")
        lines.append(f"     {wallet_url(t.wallet)}")
    return "\n".join(lines)


def fmt_discovery_report(results: dict[str, list[EnrichedTrader]], markets: Optional[list[MarketInfo]] = None) -> str:
    lines = [
        "",
        "=" * 56,
        f"  POLYMARKET TRADER DISCOVERY REPORT",
        f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "=" * 56,
        "",
    ]
    if markets:
        lines.append("  Active Markets")
        lines.append("  " + "-" * 40)
        for m in markets[:5]:
            lines.append(fmt_market_stats(m))
            lines.append("")
    for cat, traders in results.items():
        if traders:
            lines.append(fmt_expert_leaderboard(traders, cat, limit=5))
            lines.append("")
    return "\n".join(lines)


def fmt_trader_alert_html(trader: EnrichedTrader, market: Optional[MarketInfo] = None) -> str:
    lines = [
        "🔥 <b>Top Trader Alert</b>",
        "",
        f"👤 <b>{trader.name}</b> (#{trader.rank} · {trader.category})\n"
        f"  PnL: {fmt_pnl(trader.total_pnl)} | Vol: ${trader.total_volume:,.0f}\n"
        f"  <a href='{wallet_url(trader.wallet)}'>View Profile</a>",
        "",
    ]
    if market:
        vol = f"${market.volume:,.0f}" if market.volume else "N/A"
        liq = f"${market.liquidity:,.0f}" if market.liquidity else "N/A"
        outcomes_summary = " / ".join(
            f"{o.get('outcome', '?')}: {o.get('price', '?')}" for o in market.outcomes
        )
        lines.append(f"📊 <b>{market.question}</b>")
        lines.append(f"Vol: {vol} | Liq: {liq} | End: {market.end_date[:10]}")
        lines.append(f"Outcomes: {outcomes_summary}")
        lines.append("")
    if trader.positions:
        yes_pnl = sum(p.realized_pnl for p in trader.positions if p.side.upper() == "YES")
        no_pnl = sum(p.realized_pnl for p in trader.positions if p.side.upper() == "NO")
        lines.append("📈 <b>Position PnL</b>")
        lines.append(f"YES: {fmt_pnl(yes_pnl)} | NO: {fmt_pnl(no_pnl)} | Total: {fmt_pnl(yes_pnl + no_pnl)}")
        lines.append("")
    if trader.top_markets:
        lines.append("🏪 <b>Top Markets</b>")
        for slug in trader.top_markets[:5]:
            lines.append(f"  • <a href='https://polymarket.com/event/{slug}'>{slug}</a>")
        lines.append("")
    return "\n".join(lines)


def fmt_leaderboard_html(traders: list[EnrichedTrader], category: str = "OVERALL", limit: int = 10) -> str:
    lines = [
        f"🏆 <b>Expert Leaderboard — {category}</b>",
        "",
    ]
    for i, t in enumerate(traders[:limit], 1):
        lines.append(
            f"{i}. <b>{t.name}</b> | {fmt_pnl(t.total_pnl)} | Vol: ${t.total_volume:,.0f} | {len(t.positions)} pos"
        )
        if t.wallet:
            lines.append(f"   {wallet_url_short(t.wallet)}")
        lines.append("")
    return "\n".join(lines)
