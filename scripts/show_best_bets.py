
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from utils.market_discovery import MarketDiscovery, format_market_discovery, format_betting_opportunities

def main():
    discovery = MarketDiscovery()

    print("Searching for best markets...")
    scored_markets = discovery.discover_markets(limit=5, min_score=40.0)
    print("\n" + format_market_discovery(scored_markets))

    print("\nSearching for betting opportunities (arbitrage/spreads)...")
    opportunities = discovery.find_betting_opportunities(min_edge_percent=3.0)
    print("\n" + format_betting_opportunities(opportunities))

    print("\nSearching for contrarian opportunities...")
    contrarian = discovery.get_contrarian_opportunities(limit=5)
    if contrarian:
        for i, opp in enumerate(contrarian, 1):
            print(f"{i}. {opp['question']} - Recommendation: {opp['contrarian_bet']} (Reason: {opp['reason']})")
    else:
        print("No contrarian opportunities found.")

if __name__ == "__main__":
    main()
