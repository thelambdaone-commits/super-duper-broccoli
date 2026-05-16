import argparse
import os
import sys


PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from utils.crypto_market_intelligence import (  # noqa: E402
    CryptoMarketIntelligence,
    format_intelligence_report,
    report_to_json,
)
from utils.polymarket_client import PolymarketClient  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Crypto market intelligence report.")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--query", default="")
    parser.add_argument("--watchlist", default="BTC,ETH,SOL")
    parser.add_argument("--min-volume", type=float, default=10_000.0)
    parser.add_argument("--min-liquidity", type=float, default=1_000.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    client = PolymarketClient()
    try:
        markets = (
            client.search_markets(args.query, limit=args.limit)
            if args.query else client.list_markets(limit=args.limit, sort_by="volume")
        )
        watchlist = [item.strip().upper() for item in args.watchlist.split(",") if item.strip()]
        platform = CryptoMarketIntelligence(
            watchlist=watchlist,
            min_volume=args.min_volume,
            min_liquidity=args.min_liquidity,
        )
        report = platform.analyze(markets)
        print(report_to_json(report) if args.json else format_intelligence_report(report))
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
