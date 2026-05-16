import json
import time

from scrapling.fetchers import Fetcher

from config import CONFIG
from utils.polymarket_crawler.models import Trade
from utils.polymarket_crawler.categorize import categorize


def scrape_trader_trades(wallet: str, name: str) -> list[Trade]:
    url = f"https://polymarket.com/profile/{wallet}"
    try:
        page = Fetcher.get(url, follow_redirects=True, timeout=CONFIG.crawler.analytics_timeout)
    except Exception as e:
        print(f"  [analytics] {name}: fetch failed - {e}")
        return []

    raw = page.css("script#__NEXT_DATA__::text").get()
    if not raw:
        print(f"  [analytics] {name}: no __NEXT_DATA__ found")
        return []

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print(f"  [analytics] {name}: invalid JSON")
        return []

    queries = data.get("props", {}).get("pageProps", {}).get("dehydratedState", {}).get("queries", [])
    trades = []

    for q in queries:
        key = q.get("queryKey", [])
        state = q.get("state", {})
        qdata = state.get("data", {})

        # Extract current positions
        if isinstance(key, list) and len(key) >= 3 and "positions" in str(key) and qdata:
            pages = qdata.get("pages", []) if isinstance(qdata, dict) else []
            for page_data in pages:
                if isinstance(page_data, list):
                    for pos in page_data:
                        trade = _position_to_trade(pos)
                        if trade:
                            trades.append(trade)

        # Extract biggest wins
        if "biggestWins" in str(key) or "biggest-wins" in str(key) or "profile-biggest-wins" in str(key):
            wins = []
            if isinstance(qdata, list):
                wins = qdata
            elif isinstance(qdata, dict):
                wins = qdata.get("biggestWins", [])
            for w in wins:
                trade = _biggest_win_to_trade(w)
                if trade:
                    trades.append(trade)

    # Deduplicate by (market, side, size)
    seen = set()
    unique = []
    for t in trades:
        dedup_key = (t.market, t.side, round(t.size, 2))
        if dedup_key not in seen:
            seen.add(dedup_key)
            unique.append(t)

    print(f"  [analytics] {name}: {len(unique)} trades extracted")
    return unique


def _position_to_trade(pos: dict) -> Trade | None:
    slug = pos.get("slug", "")
    title = pos.get("title", "")
    size = float(pos.get("size", 0))
    avg_price = float(pos.get("avgPrice", 0))
    pnl = float(pos.get("cashPnl", 0))
    theme = categorize(slug, title)

    if not slug and not title:
        return None

    side, outcome_label = _normalize_side(pos.get("outcome", ""))

    return Trade(
        market=title or slug,
        side=side,
        size=size,
        price=avg_price,
        pnl=pnl,
        timestamp="",
        hold_time_minutes=None,
        theme=theme,
        strategy="position",
        outcome_label=outcome_label,
    )


def _biggest_win_to_trade(w: dict) -> Trade | None:
    title = w.get("marketTitle", "")
    slug = w.get("slug", "")
    size = float(w.get("initialValue", 0))
    buy_price = float(w.get("buyPrice", 50)) / 100  # stored as cents (48 = 0.48)
    pnl = float(w.get("pnl", 0))

    if not title and not slug:
        return None

    theme = categorize(slug, title)
    side, outcome_label = _normalize_side(w.get("outcome", ""))

    return Trade(
        market=title or slug,
        side=side,
        size=size,
        price=buy_price,
        pnl=pnl,
        timestamp="",
        hold_time_minutes=None,
        theme=theme,
        strategy="biggest_win",
        outcome_label=outcome_label,
    )


def _normalize_side(outcome: str) -> tuple[str, str]:
    raw = outcome.strip()
    if raw.upper() in ("YES", "NO"):
        return raw.upper(), ""
    return "", raw


def scrape_all_traders_sync(
    wallets: list[tuple[str, str]]
) -> dict[str, list[Trade]]:
    results = {}
    for i, (wallet, name) in enumerate(wallets):
        print(f"  [analytics] ({i+1}/{len(wallets)}) {name}...")
        try:
            trades = scrape_trader_trades(wallet, name)
            results[wallet] = trades
        except Exception as e:
            print(f"  [analytics] {name}: failed - {e}")
            results[wallet] = []
        time.sleep(0.3)
    return results
