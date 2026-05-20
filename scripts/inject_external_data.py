#!/usr/bin/env python3
import sys
import os
import logging

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.feature_store import FeatureStore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ExternalDataInjector")

def inject_yahoo_data(ticker: str, symbol: str):
    """
    Example of how to inject Yahoo Finance data into the bot's FeatureStore.
    Requires 'yfinance' package.
    """
    try:
        import yfinance as yf
        logger.info(f"Fetching data for {symbol} from Yahoo Finance...")
        data = yf.download(symbol, period="1d", interval="5m")

        if data.empty:
            logger.warning(f"No data found for {symbol}")
            return

        store = FeatureStore()
        count = 0
        for index, row in data.iterrows():
            ts = index.timestamp()
            # Record Close price as an external feature
            store.record_feature(ts, ticker, f"external_px_{symbol.lower()}", float(row['Close']))
            count += 1

        logger.info(f"Successfully injected {count} features for {ticker} from {symbol}")
    except ImportError:
        logger.error("yfinance not installed. Run: pip install yfinance")
    except Exception as e:
        logger.error(f"Injection failed: {e}")

if __name__ == "__main__":
    # Example usage
    inject_yahoo_data("BTC", "BTC-USD")
    inject_yahoo_data("ETH", "ETH-USD")
    inject_yahoo_data("SOL", "SOL-USD")
