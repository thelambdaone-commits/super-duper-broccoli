
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from utils.market_scanner import MarketScanner, _fmt_signal

def main():
    scanner = MarketScanner()
    scanner.TOP_MARKETS_LIMIT = 100

    print("Scanning markets for signals (limit 100)...")
    result = scanner.scan_markets()

    print(f"\nTotal markets scanned: {result.total_markets_scanned}")

    if result.winning_bets:
        print("\n--- WINNING BETS ---")
        for s in result.winning_bets:
            print(_fmt_signal(s))

    if result.trending_markets:
        print("\n--- TRENDING MARKETS ---")
        for s in result.trending_markets:
            print(_fmt_signal(s))

    if result.competitive_markets:
        print("\n--- COMPETITIVE MARKETS ---")
        for s in result.competitive_markets:
            print(_fmt_signal(s))

    if result.arbitrage_opportunities:
        print("\n--- ARBITRAGE OPPORTUNITIES ---")
        for s in result.arbitrage_opportunities:
            print(_fmt_signal(s))

    if not any([result.winning_bets, result.trending_markets, result.competitive_markets, result.arbitrage_opportunities]):
        print("\nNo high-confidence signals found for crypto markets at this time.")

if __name__ == "__main__":
    main()
