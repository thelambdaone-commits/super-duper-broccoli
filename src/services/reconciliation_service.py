from __future__ import annotations

import logging
import httpx
from typing import Any, Optional
from database.ledger_db import Ledger

logger = logging.getLogger("PositionReconciliationService")

class PositionReconciliationService:
    """
    Ensures that the bot's internal Ledger matches reality on Polymarket.
    Fetches open positions from the Polymarket API on startup and reconciles them.
    """

    def __init__(self, ledger: Ledger, wallet_address: str, freqai: Any = None):
        self.ledger = ledger
        self.wallet_address = wallet_address
        self.freqai = freqai
        self.api_url = "https://data-api.polymarket.com/positions"

    async def reconcile(self) -> dict[str, Any]:
        """
        Fetches open positions from API and syncs with Ledger.
        Returns a summary of changes.
        """
        if not self.wallet_address:
            logger.warning("Reconciliation skipped: No wallet address provided.")
            return {"status": "skipped", "reason": "no_wallet"}

        logger.info(f"🔄 [RECONCILIATION] Starting for wallet: {self.wallet_address}")

        # 1. Fetch Open Orders from CLOB (to avoid closing them if they aren't positions yet)
        open_order_ids = set()
        if self.freqai:
            try:
                open_orders = await self.freqai.get_open_orders()
                if open_orders:
                    for o in open_orders:
                        oid = o.get("id") or o.get("orderID")
                        if oid: open_order_ids.add(oid)
                    logger.info(f"Found {len(open_order_ids)} open orders on CLOB.")
            except Exception as e:
                logger.warning(f"Failed to fetch open orders during reconciliation: {e}")

        # 2. Fetch Filled Positions
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{self.api_url}?user={self.wallet_address}&limit=50")
                if response.status_code != 200:
                    logger.error(f"Failed to fetch positions from Polymarket API: {response.status_code}")
                    return {"status": "failed", "error": response.text}

                api_positions = response.json()
        except Exception as e:
            logger.error(f"Error during position reconciliation: {e}")
            return {"status": "failed", "error": str(e)}

        if not isinstance(api_positions, list):
            logger.warning(f"Unexpected response format from Polymarket API: {api_positions}")
            return {"status": "skipped", "reason": "invalid_api_response"}

        ledger_positions = self.ledger.get_open_positions()
        ledger_by_ticker = {p.get("ticker"): p for p in ledger_positions if p.get("ticker")}

        summary = {
            "api_count": len(api_positions),
            "ledger_count": len(ledger_positions),
            "synced": 0,
            "new_external": 0,
            "closed_external": 0
        }

        # 3. Check for positions in API that might be missing or need update in Ledger
        for api_pos in api_positions:
            ticker = api_pos.get("asset") or api_pos.get("token_id")
            if not ticker: continue

            size = float(api_pos.get("size", 0.0))
            price = float(api_pos.get("curPrice", 0.0))

            if ticker in ledger_by_ticker:
                # Update existing position if needed
                ledger_pos = ledger_by_ticker[ticker]
                if abs(float(ledger_pos.get("filled_qty", 0.0)) - size) > 0.01:
                    logger.info(f"Updating position {ticker}: size {ledger_pos.get('filled_qty')} -> {size}")
                    self.ledger.update_position_fill(
                        exchange_order_id=ledger_pos.get("exchange_order_id"),
                        filled_qty=size,
                        execution_price=price
                    )
                summary["synced"] += 1
            else:
                # Position exists in API but not in Ledger (e.g. manual trade or bot down during fill)
                logger.info(f"Importing external position found on-chain: {ticker}")
                import uuid
                pos_id = f"ext-{ticker[:8]}-{uuid.uuid4().hex[:4]}"
                self.ledger.record_order(
                    position_id=pos_id,
                    ticker=ticker,
                    side=api_pos.get("outcome", "YES").upper(),
                    price=price,
                    size=size,
                    filled_qty=size,
                    execution_price=price,
                    notional_usd=size * price,
                    signal_source="external_reconciliation",
                )
                summary["new_external"] += 1

        # 4. Check for positions in Ledger that are no longer in API
        api_tickers = {p.get("asset") or p.get("token_id") for p in api_positions}
        for ticker, ledger_pos in ledger_by_ticker.items():
            if ticker not in api_tickers:
                # IMPORTANT: Check if it's still an open order on CLOB before closing
                x_oid = ledger_pos.get("exchange_order_id")
                if x_oid and x_oid in open_order_ids:
                    logger.info(f"Position {ticker} not in filled positions API but still open on CLOB (Order {x_oid}). Keeping in Ledger.")
                    continue

                # Position was likely closed while the bot was down or filled and then sold
                logger.warning(f"Position {ticker} found in Ledger but NOT in Polymarket API or open orders. Marking as CLOSED_EXTERNAL.")
                self.ledger.close_position(
                    ledger_pos.get("position_id"),
                    exit_price=float(ledger_pos.get("execution_price", 0.0)),
                    exit_reason="CLOSED_WHILE_OFFLINE"
                )
                summary["closed_external"] += 1

        logger.info(f"✅ [RECONCILIATION] Completed: {summary}")
        return summary
