from utils.polymarket_crawler.models import (
    LeaderboardEntry, BiggestWin, Trade, WalletProfile,
    StrategyPattern, ScoredWallet, Decision,
)
from utils.polymarket_crawler.categorize import categorize
from utils.polymarket_crawler.trader_formatters import (
    fmt_trader_alert, fmt_expert_leaderboard, fmt_discovery_report,
    fmt_trader_alert_html, fmt_leaderboard_html,
)

try:
    from utils.polymarket_crawler.leaderboard import scrape_leaderboard_pages
    from utils.polymarket_crawler.analytics import scrape_all_traders_sync
    from utils.polymarket_crawler.traders import (
        TraderScraper, LeaderboardTrader, MarketInfo, ClosedPosition,
        TradeRecord, EnrichedTrader,
        discover_top_traders, discover_active_markets, run_discovery,
    )
    _CRAWLER_IMPORT_ERROR = None
except ModuleNotFoundError as exc:
    _CRAWLER_IMPORT_ERROR = exc

    def _raise_missing_dependency(*args, **kwargs):
        raise ModuleNotFoundError(
            "Optional Polymarket crawler dependency missing. Install crawler extras to use this feature."
        ) from _CRAWLER_IMPORT_ERROR

    scrape_leaderboard_pages = _raise_missing_dependency
    scrape_all_traders_sync = _raise_missing_dependency
    TraderScraper = LeaderboardTrader = MarketInfo = ClosedPosition = TradeRecord = EnrichedTrader = None
    discover_top_traders = discover_active_markets = run_discovery = _raise_missing_dependency

__all__ = [
    "LeaderboardEntry", "BiggestWin", "Trade", "WalletProfile",
    "StrategyPattern", "ScoredWallet", "Decision",
    "scrape_leaderboard_pages",
    "scrape_all_traders_sync",
    "categorize",
    "TraderScraper", "LeaderboardTrader", "MarketInfo", "ClosedPosition",
    "TradeRecord", "EnrichedTrader",
    "discover_top_traders", "discover_active_markets", "run_discovery",
    "fmt_trader_alert", "fmt_expert_leaderboard", "fmt_discovery_report",
    "fmt_trader_alert_html", "fmt_leaderboard_html",
]
