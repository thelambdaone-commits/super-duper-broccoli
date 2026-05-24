# 📊 Post-Trade Analytics Skill

*Moltbook-inspired Agentic Skill Document for closed-trade analysis, execution quality review, and reconciliation.*

## 1. Purpose
Explains whether returns came from alpha, timing, routing, slippage, or ledger drift after trades are closed.

## 2. Trigger Conditions
* A trade closes in paper or live mode.
* Reconciliation reports detect mismatches.
* Performance attribution requires deeper breakdown.

## 3. Execution Steps
1. Break PnL into selection, timing, and execution components.
2. Reconcile fills against ledger and execution logs.
3. Persist compact post-trade summaries into memory.
4. Surface anomalies for risk and monitoring.

## 4. Behavioral Boundaries & Constraints
* Do not rewrite historical fills.
* Do not suppress execution errors.
* Keep summaries compact and secret-free.
