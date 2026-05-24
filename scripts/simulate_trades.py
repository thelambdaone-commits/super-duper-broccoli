#!/usr/bin/env python3
import os
import sys
import time
import random
import numpy as np

# Ensure the root package is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.ledger_db import Ledger
from utils.feature_store import FeatureStore
from core.training_pipeline import TrainingPipeline

# Aesthetic styling constants
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"

def print_header(title: str):
    print(f"\n{BOLD}{CYAN}🦞 LOBSTAR QUANT AGENTIC OS — {title.upper()}{RESET}")
    print(f"{CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}")

def main():
    print_header("ML REINFORCEMENT & OUTCOME CALIBRATION LOOP")

    # 1. Initialize DBs
    db_path = "user_data/data/sim_ledger.db"
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except OSError:
            pass

    print(f"📡 {BOLD}Initializing Simulation databases...{RESET}")
    ledger = Ledger(db_path=db_path)
    store = FeatureStore(db_path="user_data/data/sim_feature_store.duckdb")

    pipeline = TrainingPipeline(
        store=store,
        min_train_samples=10,
        validation_split=0.2,
    )

    # 2. Simulate 50 closed trades for BTC with a structured overconfidence bias
    # If raw confidence is high (e.g. 0.90), we'll make actual win rate only ~60% (model is overconfident).
    # If raw confidence is low (e.g. 0.20), we'll make actual win rate ~10%.
    print(f"⚡ {BOLD}Simulating 50 paper trades with raw LOBSTAR predictions...{RESET}")
    random.seed(42)
    np.random.seed(42)

    trades = []
    ticker = "BTC"

    for i in range(50):
        side = "BUY" if random.random() > 0.4 else "SELL"
        entry_price = float(round(60000 + random.uniform(-2000, 2000), 2))
        size = float(round(0.05 + random.uniform(0.01, 0.2), 4))

        # Raw model outputs overconfident confidence
        # For long/buy signals, probability of going up is higher
        raw_confidence = float(round(random.uniform(0.60, 0.95), 4)) if side == "BUY" else float(round(random.uniform(0.05, 0.40), 4))

        # Actual win/loss resolution based on overconfidence profile
        # If confidence is > 0.8, win probability is 55%
        # If confidence is < 0.2, win probability is 10%
        if raw_confidence >= 0.7:
            is_win = random.random() < 0.55
        elif raw_confidence <= 0.3:
            is_win = random.random() < 0.10
        else:
            is_win = random.random() < 0.35

        # exit price and PnL calculation
        if is_win:
            exit_price = float(round(entry_price * (1 + random.uniform(0.02, 0.08)), 2))
            pnl = float(round(entry_price * size * random.uniform(0.02, 0.08), 2))
        else:
            exit_price = float(round(entry_price * (1 - random.uniform(0.02, 0.08)), 2))
            pnl = float(round(-entry_price * size * random.uniform(0.02, 0.08), 2))

        # Record entry
        pos = ledger.record_paper_order(
            ticker=ticker,
            side=side,
            price=entry_price,
            size=size,
            confidence=raw_confidence,
            regime_label="STABLE_TREND",
            signal_source="lobstar_llm"
        )

        # Record exit outcome
        ledger.close_paper_position(
            position_id=pos["position_id"],
            exit_price=exit_price,
            pnl=pnl,
            is_win=is_win
        )

        trades.append({
            "confidence": raw_confidence,
            "is_win": is_win,
            "pnl": pnl
        })

    # Calculate stats
    total_trades = len(trades)
    wins = sum(1 for t in trades if t["is_win"])
    losses = total_trades - wins
    win_rate = (wins / total_trades) * 100
    total_pnl = sum(t["pnl"] for t in trades)

    print(f"✅ {GREEN}Simulated 50 trades resolved successfully!{RESET}")
    print(f"📊 {BOLD}Win Rate: {win_rate:.1f}% ({wins} Wins / {losses} Losses) | Total PnL: ${total_pnl:,.2f}{RESET}")

    # 3. Trigger reinforcement calibration loop
    print(f"\n🎓 {BOLD}Running dynamic reinforcement calibration update...{RESET}")
    time.sleep(0.5)

    calibration_log = pipeline.update_calibration_from_paper_trades(ticker, ledger)

    if not calibration_log:
        print(f"❌ {RED}Reinforcement calibration failed!{RESET}")
        return

    print(f"📈 {GREEN}ML reinforcement loop complete! New calibrator fitted and saved.{RESET}")

    # 4. Extract calibrator to demonstrate probability correction
    calibrator = pipeline._calibrators[ticker]

    # Visual ASCII Calibration comparison table
    print_header("PROBABILITY CALIBRATION CURVE")
    print(f"{'Raw Confidence':<18} | {'Calibrated (Reinforced)':<24} | {'Status Adjustment':<20}")
    print(f"━━━━━━━━━━━━━━━━━━━┿━━━━━━━━━━━━━━━━━━━━━━━━━━┿━━━━━━━━━━━━━━━━━━━━")

    test_probas = [0.90, 0.80, 0.70, 0.50, 0.30, 0.10]
    for raw in test_probas:
        raw_arr = np.zeros((1, 2))
        raw_arr[0, 1] = raw
        raw_arr[0, 0] = 1.0 - raw

        calibrated = calibrator.predict_proba(raw_arr)[0, 1]
        diff = calibrated - raw

        # Sizing and status indicator
        if diff < -0.15:
            adj = f"{RED}🚨 Overconfident (-{abs(diff)*100:.1f}%){RESET}"
        elif diff < -0.05:
            adj = f"{YELLOW}🟡 Softening (-{abs(diff)*100:.1f}%){RESET}"
        elif diff > 0.05:
            adj = f"{GREEN}🟢 Hardening (+{abs(diff)*100:.1f}%){RESET}"
        else:
            adj = f"{RESET}⚪ Stable ({diff*100:+.1f}%){RESET}"

        print(f" {raw*100:>5.1f}%             │  {calibrated*100:>5.1f}%                 │ {adj}")

    # 5. Kelly Criterion sizing simulation comparison
    print_header("RISK PROTECTION & KELLY CAPITAL SIZING")

    # Kelly Formula: f = p - (1-p)/b
    # Assume payout b = 1.0 (even money YES/NO contract)
    print(f"{BOLD}Simulating Kelly Criterion capital allocation for a high-risk trade with a raw confidence of 90%:{RESET}")
    raw_p = 0.90
    raw_kelly = (2 * raw_p - 1) * 100  # f = 2p - 1 for b = 1

    # Calibrated probability
    raw_arr = np.zeros((1, 2))
    raw_arr[0, 1] = raw_p
    raw_arr[0, 0] = 1.0 - raw_p
    cal_p = calibrator.predict_proba(raw_arr)[0, 1]
    cal_kelly = max(0.0, (2 * cal_p - 1) * 100)

    print(f"\n  • {BOLD}Using Raw Prediction (90% Win Prob):{RESET}")
    print(f"    Sizing: {RED}{raw_kelly:.1f}%{RESET} of total portfolio capital engaged.")
    print(f"    {RED}⚠️ RISK: Extremely high risk of ruin due to overconfident model predictions.{RESET}")

    print(f"\n  • {BOLD}Using Calibrated Prediction ({cal_p*100:.1f}% Win Prob):{RESET}")
    print(f"    Sizing: {GREEN}{cal_kelly:.1f}%{RESET} of total portfolio capital engaged.")
    print(f"    {GREEN}🛡️ PROTECTION: Capital protected by reinforcing wins/losses into probability calibration.{RESET}")

    # 6. Overall reinforcement metrics
    print_header("REINFORCEMENT METRICS SUMMARY")
    print(f"  • Raw Brier Score:         {BOLD}{RED}{calibration_log['raw_brier']:.6f}{RESET} (Initial calibration error)")
    print(f"  • Calibrated Brier Score:  {BOLD}{GREEN}{calibration_log['calibrated_brier']:.6f}{RESET} (Reinforced calibration error)")
    print(f"  • Brier Improvement:      {BOLD}{GREEN}+{calibration_log['brier_improvement']:.6f}{RESET} (Lower is better)")
    print(f"  • Fusion Mode Utilized:    {BOLD}{CYAN}{calibration_log['fusion_mode'].upper()}{RESET}")
    print(f"  • Reinforcement Samples:   {BOLD}{total_trades} trades{RESET}")
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"✨ {BOLD}{GREEN}Lobstar Quant Agentic OS reinforcement loop is operating with peak efficiency!{RESET}\n")

if __name__ == "__main__":
    main()
