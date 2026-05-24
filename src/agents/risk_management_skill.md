# 🛡️ Risk Management Skill

*Moltbook-inspired Agentic Skill Document for consecutive loss tracking, drawdown guard, API health monitoring, and emergency kill-switch enforcement.*

---

## 1. Purpose
Enforces strict capital preservation by monitoring drawdown, consecutive losses, API health, and balance anomalies. Blocks trading immediately when risk thresholds are breached. No trade executes without passing all deterministic risk gates.

---

## 2. Trigger Conditions
- **Pre-Trade Validation**: Every order signal entering the execution pipeline.
- **Drawdown Threshold Breach**: Portfolio drawdown exceeds 5% (scaling) or 15% (hard kill).
- **Consecutive Loss Detection**: Three or more losing trades in a row.
- **API Health Degradation**: Latency spikes or error rate increase.
- **Balance Anomaly**: Unexpected capital change or capital drops below 5 USD.

---

## 3. Execution Steps

### Step A: Pre-Trade Risk Checklist
Before any order, verify ALL of the following:

| Check | Condition | Action on Failure |
|---|---|---|
| Consecutive Losses | `< 3` in a row | Hard block — escalate to security |
| Daily Loss | `< 10%` of starting capital | Hard block |
| Capital Floor | `>= 5 USD` | Hard block — halt all trading |
| Market Manipulation | Low probability score | Hard block |
| API Latency | Stable, no spikes | Hard block — retry or abort |
| Spread Quality | Tight enough for edge | Hard block |
| Edge vs Fees | Edge > total fees | Hard block |

If **any** check fails, reject the order immediately with a logged reason.

### Step B: Drawdown Monitoring & Kill-Switch
1. Compute current portfolio drawdown: `(peak_capital - current_capital) / peak_capital`.
2. If drawdown `> 5%`:
   - Scale down all position sizes proportionally.
3. If drawdown `> 15%`:
   - **Immediately halt all trading.**
   - Log: `🚨 [RISK KILL-SWITCH: Drawdown > 15%] Trading halted.`
   - Require manual re-authorization from Security Specialist before any new trade.

### Step C: Position Sizing Guard
1. Default: `1 USD` per order.
2. Per-market max: `5%` of total capital.
3. Total exposure max: `20%` of total capital.
4. Kelly-calibrated sizing: never exceed Kelly-optimal fraction.
5. **Never all-in.**

### Step D: Emergency Safety Protocol
Immediately disable trading if any of the following are detected:
- Drawdown `> 15%`
- Capital drops below `5 USD`
- API error rate spikes
- Unexpected balance change
- Inconsistent market data
- Unresolved order state
- 3 consecutive losses

Recovery requires explicit manual re-authorization from the Security Specialist.

---

## 4. Behavioral Boundaries & Constraints
- > [!IMPORTANT]
  > **Capital Preservation First**: Profit generation is secondary. No trade may proceed if any risk gate fails.
- > [!WARNING]
  > **Kill-Switch is Absolute**: Once triggered, no trading resumption is permitted without Security Specialist re-authorization. Bypassing the kill-switch is forbidden.
- > [!CAUTION]
  > **HMM Regime Awareness**: Trading must be restricted or scaled based on current HMM volatility classification. High-volatility regimes require tighter sizing and may block new entries entirely.
- > [!CAUTION]
  > **Ledger Reserve Rule**: Capital must be reserved in `ledger_db.py` before any trade executes. No trade without a corresponding ledger reservation.
- > [!CAUTION]
  > **Zero Tolerance on Capital Floor**: If capital falls below 5 USD at any point, all trading stops immediately and does not resume until capital is restored above the threshold.
