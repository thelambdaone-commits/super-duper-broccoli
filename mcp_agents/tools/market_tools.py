import json
import numpy as np
from typing import Optional
from user_data.strategies.hmm_filter import HMMRegimeFilter
from user_data.strategies.arbitrage_scanner import ArbitrageScanner
from utils.regime_utils import get_regime_label

def get_market_tools(mcp, hmm: Optional[HMMRegimeFilter], arb_scanner: Optional[ArbitrageScanner]):
    @mcp.tool(
        name="get_market_regime",
        description="Queries the live HMM filter status, regime label, and Dissimilarity Index for OOD detection.",
    )
    def get_market_regime(
        ticker: str = "SOL",
        returns_json: str = "",
    ) -> dict:
        if hmm is None:
            return {"error": "HMM filter not initialized", "regime": "UNKNOWN"}

        if returns_json:
            returns = np.array(json.loads(returns_json), dtype=np.float32)
        else:
            returns = np.zeros(100, dtype=np.float32)

        state, label = hmm.predict_with_label(returns)
        di = hmm.compute_dissimilarity_index(returns)
        allowed, reason = hmm.is_trading_allowed(returns)

        return {
            "ticker": ticker,
            "hmm_state": int(state),
            "regime_label": label,
            "dissimilarity_index": round(float(di), 6),
            "trading_allowed": allowed,
            "reason": reason,
        }

    @mcp.tool(
        name="get_arbitrage_opportunities",
        description="Returns current arbitrage opportunities detected by ArbitrageScanner.",
    )
    def get_arbitrage_opportunities() -> dict:
        if arb_scanner is None:
            return {"error": "ArbitrageScanner not initialized"}
        return {
            "opportunity_count": arb_scanner.opportunity_count,
            "opportunities": arb_scanner.get_active_opportunities(),
        }
