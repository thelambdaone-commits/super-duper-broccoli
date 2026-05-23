import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

from core.container import ServiceContainer
from core.autonomous_trading_loop import AutonomousTradingLoop, MarketFeatures
from utils.market_scanner import MarketScanner

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("WinAnalysis")

async def analyze_winning_trade():
    logger.info("Starting End-to-End Win Analysis...")
    
    # 1. Setup Environment
    container = ServiceContainer.get_instance()
    scanner = MarketScanner() # Uses PolymarketClient internally
    loop = AutonomousTradingLoop(
        ledger=container.ledger,
        risk_engine=container.risk,
        feature_store=container.store,
        executor=container.executor
    )

    # 2. Data Acquisition
    logger.info("Fetching latest market features...")
    scan_result = scanner.scan_markets()
    features = scanner.get_strategy_features()
    
    if not features:
        logger.warning("No live market features found. Using dummy feature for analysis.")
        features = [{
            "ticker": "BTC-PRO-2026",
            "market_id": "btc-pro-2026",
            "mid_price": 0.45,
            "volume": 150000.0,
            "liquidity": 12000.0,
            "spread_bps": 45.0,
            "known_wallet_flow_score": 0.75,
            "hmm_regime": "LOW_VOLATILITY"
        }]

    target = features[0]
    market_id = target.get("market_id") or target.get("ticker")
    logger.info(f"Targeting market: {market_id}")

    # 3. Entry Condition & Signal Selection
    logger.info("Evaluating entry conditions via Autonomous Selector...")
    # Simulate the selection process
    candidates = loop._approved_strategy_signals(MarketFeatures.from_mapping(target))
    if not candidates:
        logger.warning("No strategies approved the current market state. Seeding a high-confidence signal for analysis.")
        from user_data.strategies.base_strategy import StrategySignal
        signal = StrategySignal(
            strategy_id="analysis_pro_v1",
            market_id=market_id,
            ticker=market_id,
            side="BUY",
            price=target.get("mid_price", 0.5),
            confidence=0.85,
            edge=0.12,
            reason="Strong momentum alignment + low RSI + positive whale flow",
            metadata={"hmm_regime": "LOW_VOLATILITY"}
        )
    else:
        signal = candidates[0]

    # 4. Risk Gating & Sizing
    sizing = loop._compute_sizing(signal)
    logger.info(f"Risk Engine Output: {sizing}")
    
    # 5. Position Opening (PAPER for analysis safety)
    action = loop._open_paper_position(signal, sizing.get("size", 1.0))
    if action.status != "OPENED":
        logger.error(f"Failed to open position: {action.reason}")
        return

    pos_id = action.position_id
    entry_price = signal.price
    tp_pct = loop._take_profit_for_signal(signal)
    sl_pct = loop._stop_loss_for_signal(signal)
    
    logger.info(f"TRADE OPENED | ID: {pos_id} | Entry: ${entry_price:.4f}")
    logger.info(f"SETTINGS | TP: {tp_pct:.1%} | SL: {sl_pct:.1%}")

    # 6. Result Calculation (Simulating a Win)
    logger.info("Simulating market move towards Take Profit...")
    # Hit TP: price goes up by TP_PCT + small margin
    exit_price = entry_price * (1.0 + tp_pct + 0.01)
    pnl = loop._position_pnl(signal.side, entry_price, exit_price, sizing.get("size", 1.0))
    
    logger.info(f"MARKET EVENT | Price moved to ${exit_price:.4f} | Condition: TP_HIT")
    
    # 7. Closing & Ledger Update
    container.ledger.close_paper_position(pos_id, exit_price=exit_price, pnl=pnl, is_win=True)
    logger.info(f"TRADE CLOSED | Exit: ${exit_price:.4f} | PnL: ${pnl:.4f} (WIN)")

    # 8. Report Data Collection
    report = {
        "objective": "Verify the full signal-to-ledger chain with winning resolution.",
        "entry_criteria": {
            "strategy": signal.strategy_id,
            "edge": signal.edge,
            "confidence": signal.confidence,
            "reason": signal.reason
        },
        "market": market_id,
        "parameters": {
            "tp": tp_pct,
            "sl": sl_pct,
            "sizing": sizing
        },
        "outcome": {
            "entry": entry_price,
            "exit": exit_price,
            "pnl": pnl,
            "status": "WINNER"
        }
    }
    
    print("\n" + "="*50)
    print("WINNING TRADE ANALYSIS REPORT")
    print("="*50)
    for k, v in report.items():
        print(f"{k.upper()}: {v}")
    print("="*50)

if __name__ == "__main__":
    asyncio.run(analyze_winning_trade())
