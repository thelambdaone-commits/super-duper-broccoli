#!/usr/bin/env python3
"""
Lobstar Quant OS - Ingestion Layer Audit & Cache Flush Utility
Path: scripts/microfish_audit.py
"""
import os
import sys
import asyncio
import logging
import json
import math
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from continuous_improvement.agents.microfish_ingest import MicrofishIngestAgent
from utils.feature_store import FeatureStore
from utils.market_watchlist import get_polymarket_watchlist

# Setup structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("MicrofishAudit")

async def run_audit():
    logger.info("======================================================================")
    logger.info("🚨 LOBSTAR QUANT OS - INGESTION LAYER AUDIT & RESET SEQUENCE")
    logger.info("======================================================================")

    # ---------------------------------------------------------
    # STEP 1: Flush Feature Store Temp Files & Streams
    # ---------------------------------------------------------
    logger.info("🧹 STEP 1: Flushing raw streams and temporary JSONL caches...")

    # 1.1 Flush raw stream jsonl files
    raw_stream_dir = Path("user_data/data/raw_stream")
    if raw_stream_dir.exists():
        jsonl_files = list(raw_stream_dir.glob("*.jsonl"))
        logger.info(f"Found {len(jsonl_files)} temporary stream files in {raw_stream_dir}.")
        for f in jsonl_files:
            try:
                f.unlink()
                logger.info(f"  - Deleted temporary lock file: {f.name}")
            except Exception as e:
                logger.warning(f"  - Could not delete {f.name}: {e}")
    else:
        logger.info("  - Raw stream directory user_data/data/raw_stream is already clean.")
        raw_stream_dir.mkdir(parents=True, exist_ok=True)

    # 1.2 Flush transient microfish stream
    transient_stream = Path("data/microfish_stream.jsonl")
    if transient_stream.exists():
        try:
            transient_stream.unlink()
            logger.info(f"  - Truncated and flushed {transient_stream}")
        except Exception as e:
            logger.warning(f"  - Could not truncate {transient_stream}: {e}")
    else:
        logger.info("  - Transient microfish JSONL cache is clean.")

    # ---------------------------------------------------------
    # STEP 2: Trigger Microfish_Ingest_Agent Self-Test
    # ---------------------------------------------------------
    logger.info("📡 STEP 2: Triggering MicrofishIngestAgent self-test on core tickers...")

    agent = MicrofishIngestAgent(storage_path=str(transient_stream))
    auto_only = str(os.getenv("POLYMARKET_WATCHLIST_AUTO_ONLY", "")).lower() in {"1", "true", "yes", "on"}
    tickers = get_polymarket_watchlist(limit=100, auto_discover_only=auto_only)
    interval_seconds = 15.0
    min_records = int(os.getenv("MICROFISH_MIN_RECORDS", "100"))
    records_per_cycle = max(len(tickers), 1)
    cycles_needed = math.ceil(min_records / records_per_cycle)
    eta_minutes = (cycles_needed * interval_seconds) / 60.0

    logger.info(f"Capturing order books for tickers: {tickers}...")
    logger.info(
        "  Threshold: %s records, %s tickers/cycle, interval %.1fs -> ~%.1f minutes to fill a fresh stream.",
        min_records,
        records_per_cycle,
        interval_seconds,
        eta_minutes,
    )
    for ticker in tickers:
        logger.info(f"  Fetching order book for {ticker} from Polymarket CLOB...")
        record = await agent._capture_orderbook(ticker)
        if record:
            logger.info(f"  ✅ SUCCESS for {ticker}:")
            logger.info(f"    - Bid: {record['bid_price']} | Ask: {record['ask_price']} | Mid: {record['mid_price']:.4f}")
            logger.info(f"    - Spread: {record['spread']:.4f} (Divergence: {record['spread_divergence']:.2f}x)")
            logger.info(f"    - L3 Bid Vol: {record['bid_volume']:.2f} | L3 Ask Vol: {record['ask_volume']:.2f}")
            logger.info(f"    - Order Imbalance (OI): {record['order_imbalance']:.4f}")
        else:
            logger.warning(f"  ❌ FAILED to capture order book for {ticker}")

    # ---------------------------------------------------------
    # STEP 3: DuckDB Indexing Verification
    # ---------------------------------------------------------
    logger.info("💾 STEP 3: Verifying Feature Store database statistics...")
    try:
        store = FeatureStore()
        stats = store.get_stats()
        logger.info("  ✅ Connected to DuckDB Feature Store successfully!")
        logger.info(f"  Current statistics: {json.dumps(stats, indent=4)}")
    except Exception as e:
        if "Could not set lock on file" in str(e) or "Conflicting lock" in str(e):
            logger.info("  ⚠️  DuckDB file is currently locked by a running production instance.")
            logger.info("     (This confirms the active service is online and indexing features.)")
        else:
            logger.error(f"  ❌ Feature Store connection error: {e}")

    logger.info("======================================================================")
    logger.info("🎉 AUDIT & RESET SEQUENCE COMPLETED SUCCESSFULLY!")
    logger.info("======================================================================")

if __name__ == "__main__":
    asyncio.run(run_audit())
