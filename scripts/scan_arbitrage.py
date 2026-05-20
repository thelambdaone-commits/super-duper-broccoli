
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from utils.polymarket_client import PolymarketClient
from user_data.strategies.arbitrage_scanner import ArbitrageScanner

def main():
    client = PolymarketClient()
    scanner = ArbitrageScanner(min_profit_threshold=0.01)

    print("Fetching markets...")
    markets = client.list_markets(limit=100, sort_by="volume")

    market_outcomes = {}
    for m in markets:
        if m.active and not m.closed:
            # For binary markets, outcomes are YES/NO
            if len(m.outcomes) == 2:
                market_outcomes[m.slug] = {
                    "YES": m.yes_price,
                    "NO": m.no_price
                }

    print(f"Scanning {len(market_outcomes)} binary markets for sum inefficiency...")
    opportunities = scanner.scan_sum_inefficiency(market_outcomes)

    if opportunities:
        print("\n--- ARBITRAGE OPPORTUNITIES (SUM INEFFICIENCY) ---")
        for opp in opportunities:
            print(f"Market: {opp['market_id']}")
            print(f"  Total Prob: {opp['total_probability']}")
            print(f"  Deviation: {opp['deviation']}")
            print(f"  Action: {opp['action']} (Conf: {opp['confidence']:.2%})")
            print(f"  Details: Underpriced={opp['underpriced_outcome']} ({opp['underpriced_prob']:.4f}), Overpriced={opp['overpriced_outcome']} ({opp['overpriced_prob']:.4f})")
    else:
        print("\nNo sum inefficiency opportunities found.")

if __name__ == "__main__":
    main()
