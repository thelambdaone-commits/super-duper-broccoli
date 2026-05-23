import json
import time

from scrapling.fetchers import Fetcher

from config import CONFIG
from utils.polymarket_crawler.models import LeaderboardEntry, BiggestWin


def scrape_leaderboard() -> tuple[list[LeaderboardEntry], list[BiggestWin]]:
    url = CONFIG.leaderboard_url
    print(f"[leaderboard] Fetching {url}")

    page = Fetcher.get(url, follow_redirects=True)
    print(f"[leaderboard] Status {page.status}")

    raw = page.css("script#__NEXT_DATA__::text").get()
    if not raw:
        for s in page.css("script"):
            t = s.text
            if t and "__NEXT_DATA__" in t:
                raw = t
                break
    if not raw:
        for s in page.css("script"):
            t = s.text
            if t and '"props"' in t and 'pageProps' in t:
                raw = t
                break

    if not raw:
        raise RuntimeError("Could not find __NEXT_DATA__ in page")

    data = json.loads(raw)
    queries = data["props"]["pageProps"]["dehydratedState"]["queries"]

    profit_entries = []
    volume_entries = []
    biggest_wins = []

    for q in queries:
        key = q["queryKey"]
        items = q["state"]["data"]
        if not isinstance(items, list) or not items:
            continue
        if key[1] == "profit":
            profit_entries = [_parse_leaderboard_item(i) for i in items]
        elif key[1] == "volume":
            volume_entries = [_parse_leaderboard_item(i) for i in items]
        elif key[1] == "biggestWins":
            biggest_wins = [_parse_biggest_win(i) for i in items]

    merged = _merge_leaderboard(profit_entries, volume_entries)

    print(f"[leaderboard] {len(merged)} wallets, {len(biggest_wins)} biggest wins")
    return merged, biggest_wins


def _parse_leaderboard_item(item: dict) -> LeaderboardEntry:
    return LeaderboardEntry(
        rank=item["rank"],
        proxy_wallet=item["proxyWallet"].lower(),
        name=item.get("name") or item.get("pseudonym", ""),
        pseudonym=item.get("pseudonym", ""),
        amount=item.get("amount", 0),
        pnl=item.get("pnl", 0),
        volume=item.get("volume", 0),
        realized=item.get("realized", 0),
        unrealized=item.get("unrealized", 0),
    )


def _parse_biggest_win(item: dict) -> BiggestWin:
    return BiggestWin(
        win_rank=int(item.get("winRank", 0)),
        proxy_wallet=item.get("proxyWallet", "").lower(),
        user_name=item.get("userName", ""),
        event_slug=item.get("eventSlug", ""),
        event_title=item.get("eventTitle", ""),
        initial_value=item.get("initialValue", 0),
        final_value=item.get("finalValue", 0),
        pnl=item.get("pnl", 0),
    )


def _merge_leaderboard(
    profit: list[LeaderboardEntry], volume: list[LeaderboardEntry]
) -> list[LeaderboardEntry]:
    by_wallet = {}
    for e in profit:
        by_wallet[e.proxy_wallet] = e
    for e in volume:
        if e.proxy_wallet not in by_wallet:
            by_wallet[e.proxy_wallet] = e
    return list(by_wallet.values())


def scrape_leaderboard_pages(num_pages: int = 1) -> tuple[list[LeaderboardEntry], list[BiggestWin]]:
    all_wallets = []
    all_wins = []
    seen_wallets = set()

    for page_num in range(1, num_pages + 1):
        try:
            if page_num == 1:
                wallets, wins = scrape_leaderboard()
            else:
                wallets, wins = _scrape_page(page_num)
            for w in wallets:
                if w.proxy_wallet not in seen_wallets:
                    all_wallets.append(w)
                    seen_wallets.add(w.proxy_wallet)
            all_wins.extend(wins)
            if page_num < num_pages:
                time.sleep(1)
        except Exception as e:
            print(f"[leaderboard] Page {page_num} failed: {e}")
            break

    return all_wallets, all_wins


def _scrape_page(page_num: int) -> tuple[list[LeaderboardEntry], list[BiggestWin]]:
    url = f"{CONFIG.leaderboard_url}?page={page_num}"
    print(f"[leaderboard] Fetching page {page_num}: {url}")
    page = Fetcher.get(url, follow_redirects=True)
    raw = page.css("script#__NEXT_DATA__::text").get()
    if not raw:
        for s in page.css("script"):
            t = s.text
            if t and "__NEXT_DATA__" in t:
                raw = t
                break
    if not raw:
        return [], []

    data = json.loads(raw)
    queries = data["props"]["pageProps"]["dehydratedState"]["queries"]
    profit_entries = []
    biggest_wins = []

    for q in queries:
        key = q["queryKey"]
        items = q["state"]["data"]
        if not isinstance(items, list) or not items:
            continue
        kw = {"pageNum": page_num}
        if list(key[1:4]) == ["profit", "1d", page_num]:
            profit_entries = [_parse_leaderboard_item(i) for i in items]
        elif key[1] == "biggestWins":
            biggest_wins = [_parse_biggest_win(i) for i in items]

    return profit_entries, biggest_wins
