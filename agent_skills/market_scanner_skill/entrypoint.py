from utils.market_scanner import MarketScanner

def scan_polymarket(limit: int = 30) -> dict:
    """Executes a live or simulated scan of prediction contracts."""
    scanner = MarketScanner()
    result = scanner.scan_markets()
    sentiment = scanner.get_aggregate_sentiment()
    
    return {
        "status": "SUCCESS",
        "limit_scanned": limit,
        "sentiment_label": sentiment["sentiment"],
        "bullish_pct": sentiment["bullish_pct"],
        "total_analyzed": sentiment["total"],
        "signals_detected": len(result.trending_markets) + len(result.arbitrage_opportunities) + len(result.winning_bets) + len(result.competitive_markets)
    }
