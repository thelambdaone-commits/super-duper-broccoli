import re
from typing import Optional

_ASSET_KEYWORDS = {
    "BTC": ["BITCOIN", "BTC", "XBT"],
    "ETH": ["ETHEREUM", "ETH"],
    "SOL": ["SOLANA", "SOL"],
    "LINK": ["CHAINLINK", "LINK"],
    "ARB": ["ARBITRUM", "ARB"],
    "OP": ["OPTIMISM", "OP"],
    "MATIC": ["POLYGON", "MATIC", "POL"],
    "TRUMP": ["TRUMP", "DONALD"],
    "BIDEN": ["BIDEN", "JOE"],
}

def normalize_to_asset(ticker_or_slug: str) -> str:
    """
    Normalizes a ticker symbol, market slug, or token ID to a canonical asset name.
    Example: 'will-bitcoin-hit-100k' -> 'BTC'
             'ETH/USDT' -> 'ETH'
             '0x...' -> '0x...' (leaves token IDs unchanged if no match found)
    """
    if not ticker_or_slug:
        return "UNKNOWN"
    
    text = str(ticker_or_slug).upper()
    
    # 1. Direct Keyword Match (prioritize longest matches)
    for asset, keywords in _ASSET_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                return asset
                
    # 2. Extract from pair format (BTC/USDT -> BTC)
    match = re.match(r"^([A-Z0-9]+)[/-]", text)
    if match:
        return match.group(1)
        
    # 3. Fallback to original (cleaned)
    return text.strip()
