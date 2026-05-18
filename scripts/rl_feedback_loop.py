import os
import sys
import json
import time
import logging

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ledger.ledger_db import Ledger

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("RLFeedbackLoop")

WEIGHTS_PATH = "data/ml_weights.json"

def run_rl_feedback_loop() -> None:
    print("\n" + "═" * 60)
    print(" 📡 LOBSTAR CRYPTO SENTIMENT — REINFORCEMENT LEARNING TUNER")
    print("═" * 60)

    # 1. Load dynamic weights
    os.makedirs(os.path.dirname(WEIGHTS_PATH), exist_ok=True)
    weights = {}
    if os.path.exists(WEIGHTS_PATH):
        try:
            with open(WEIGHTS_PATH, "r", encoding="utf-8") as f:
                weights = json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read existing weights: {e}")

    # Standard setup
    if "bias_factors" not in weights:
        weights["bias_factors"] = {"BTC": 1.0, "ETH": 1.0, "SOL": 1.0}
    if "version" not in weights:
        weights["version"] = 1
    if "deviation_reports" not in weights:
        weights["deviation_reports"] = []
    if "processed_positions" not in weights:
        weights["processed_positions"] = []

    processed = set(weights["processed_positions"])

    # 2. Fetch paper outcomes
    try:
        ledger = Ledger()
        closed_positions = ledger.get_paper_positions(status="CLOSED")
    except Exception as e:
        logger.error(f"Failed to retrieve closed positions from Ledger: {e}")
        return

    logger.info(f"Retrieved {len(closed_positions)} closed simulated paper positions.")
    new_wins = 0
    new_losses = 0

    lambda_smooth = float(os.getenv("RL_SMOOTHING_FACTOR", "0.98"))
    lambda_smooth = max(0.8, min(lambda_smooth, 0.999))

    for pos in closed_positions:
        pos_id = pos["position_id"]
        if pos_id in processed:
            continue

        ticker = pos["ticker"].upper()
        pnl = pos.get("pnl") or 0.0
        is_win = pos.get("is_win")

        # Fallback to verify winning status if is_win isn't explicitly set
        pnl_win = pnl > 0
        actual_win = (is_win == 1) or pnl_win

        if ticker not in weights["bias_factors"]:
            weights["bias_factors"][ticker] = 1.0

        old_bias = weights["bias_factors"][ticker]

        # Calculate risk-adjusted R-multiple
        risk_capital = float(pos.get("capital_virtual") or 0.0)
        if risk_capital <= 0.0:
            # Fallback based on entry price and size
            entry_price = float(pos.get("entry_price") or 0.5)
            size = float(pos.get("size") or 1.0)
            risk_capital = entry_price * size

        if risk_capital <= 0.0:
            risk_capital = 1.0

        r_multiple = pnl / risk_capital

        if actual_win:
            # Dynamic positive reinforcement scaled by R-multiple edge quality
            reward = 1.0 + min(0.20, 0.05 * r_multiple)
            weights["bias_factors"][ticker] = min(2.0, max(0.2, lambda_smooth * old_bias + (1.0 - lambda_smooth) * reward))
            new_wins += 1
            logger.info(f"🏆 WIN  [{ticker}] {pos_id} PnL={pnl:.4f} ({r_multiple:+.2f}R). Bias: {old_bias:.3f} -> {weights['bias_factors'][ticker]:.3f}")
        else:
            # Gentle penalty for minor drawdowns/scratch trades, steeper for full losses
            reward = 1.0 - min(0.30, 0.08 * abs(r_multiple))
            weights["bias_factors"][ticker] = min(2.0, max(0.2, lambda_smooth * old_bias + (1.0 - lambda_smooth) * reward))
            new_losses += 1
            report = {
                "position_id": pos_id,
                "ticker": ticker,
                "side": pos.get("side"),
                "entry_price": pos.get("entry_price"),
                "exit_price": pos.get("exit_price"),
                "confidence": pos.get("confidence"),
                "pnl": pnl,
                "timestamp": time.time()
            }
            weights["deviation_reports"].append(report)
            logger.info(f"⚠️ LOSS [{ticker}] {pos_id} PnL={pnl:.4f} ({r_multiple:+.2f}R). Bias: {old_bias:.3f} -> {weights['bias_factors'][ticker]:.3f}")

        processed.add(pos_id)

    weights["processed_positions"] = list(processed)

    # 3. Save weights
    try:
        with open(WEIGHTS_PATH, "w", encoding="utf-8") as f:
            json.dump(weights, f, indent=2)
        logger.info(f"Dynamic weights saved to {WEIGHTS_PATH}")
    except Exception as e:
        logger.error(f"Failed to save weights: {e}")

    # 4. High-Aesthetic Dashboard
    print("\n📊 REINFORCEMENT TRAINING SUMMARY:")
    print(f"  • New Resolved Trades: {new_wins + new_losses} ({new_wins} Wins, {new_losses} Losses)")
    print(f"  • Total Archived Deviation Reports: {len(weights['deviation_reports'])}")
    print("\n🎯 UPDATED ML CONFIDENCE BIASES:")
    for ticker, bias in weights["bias_factors"].items():
        bar_len = int(bias * 10)
        bar = "█" * bar_len + "░" * (20 - bar_len)
        print(f"  • {ticker:<4}: {bar} {bias:.3f}x")
    print("═" * 60 + "\n")

if __name__ == "__main__":
    run_rl_feedback_loop()
