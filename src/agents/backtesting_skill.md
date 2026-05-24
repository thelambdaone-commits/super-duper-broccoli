# 🧪 Backtesting Skill

*Moltbook-inspired Agentic Skill Document for walk-forward validation, replay integrity, and simulation cost modeling.*

## 1. Purpose
Keeps backtests honest by enforcing time-series aware evaluation, realistic costs, and regime-aware replay logic.

## 2. Trigger Conditions
* A strategy is retrained or revalidated.
* A simulation or replay job starts.
* Performance drift or leakage is suspected.

## 3. Execution Steps
1. Use walk-forward or time-based splits.
2. Model fees, spread, slippage, and latency.
3. Compare regime-aware and regime-agnostic results.
4. Record compact attribution for later analysis.

## 4. Behavioral Boundaries & Constraints
* Never treat backtest results as live trading approval.
* Never ignore execution costs.
* Never allow lookahead leakage into validation.
