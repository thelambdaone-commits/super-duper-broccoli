import os
import sqlite3
import requests
import logging
from typing import List, Dict

# Configuration
DATA_PATH = os.getenv("DATA_PATH", "data")
LEDGER_DB_PATH = os.path.join(DATA_PATH, "ledger.db")
POLYMARKET_USER = os.getenv("POLYMARKET_TARGET_USER", "0xe29aff6a6ae1e1d6a3a1c4c904f2957afa98cda0")
POLYMARKET_API = f"https://data-api.polymarket.com/positions?user={POLYMARKET_USER}"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("PositionSync")

def fetch_live_positions() -> List[Dict]:
    try:
        response = requests.get(POLYMARKET_API, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Failed to fetch positions from API: {e}")
        return []

def sync_positions():
    live_positions = fetch_live_positions()
    if not live_positions:
        logger.info("No positions found or API error. Skipping sync.")
        return

    conn = sqlite3.connect(LEDGER_DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        for pos in live_positions:
            # Polymarket API structure typically includes:
            # market, outcome, size, avgPrice, currentValue
            ticker = pos.get("market")
            size = float(pos.get("size", 0))
            entry_price = float(pos.get("avgPrice", 0))
            current_price = float(pos.get("currentPrice", 0)) # Assuming API provides mark

            # Upsert into ledger positions table
            cursor.execute("""
                INSERT INTO positions (position_id, ticker, side, size, entry_price, current_price, status)
                VALUES (?, ?, ?, ?, ?, ?, 'OPEN')
                ON CONFLICT(position_id) DO UPDATE SET
                    size=excluded.size,
                    current_price=excluded.current_price
            """, (f"api_{ticker}", ticker, "BUY", size, entry_price, current_price))
        
        conn.commit()
        logger.info(f"Successfully synced {len(live_positions)} positions.")
    except Exception as e:
        logger.error(f"Database sync error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    sync_positions()
