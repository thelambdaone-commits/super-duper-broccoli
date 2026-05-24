# ⚡ Adaptive Execution Skill

*Moltbook-inspired Agentic Skill Document for volatility-adaptive routing, maker/taker execution, and arbitrage netting.*

---

## 1. Purpose
Defines the rules for routing trading execution based on real-time market volatility. By checking the HMM regime, the system routes orders to capture rebates in quiet markets (Maker mode) or avoid adverse selection in active markets (Taker mode), with instant bypass for arbitrage anomalies.

---

## 2. Trigger Conditions
* **Execution Signal**: A signal passes the predictive opinion check and is validated for size and risk.
* **Arbitrage Alert**: An extreme price discrepancy or conditional overpricing is identified in the orderbook.

---

## 3. Execution Steps

### Step A: Regime Check
1. Retrieve the current HMM market regime.
2. If an arbitrage netting condition is detected:
   * Skip all queues.
   * Route instantly to CLOB outcome netting to capture risk-free profit.

### Step B: Maker vs Taker Routing
1. **Low Volatility (`'LOW_VOLATILITY'`)**:
   * Route to `PassiveExecutor` (Maker mode).
   * Submit post-only orders to collect liquidity provider spread rebates.
2. **High Volatility / Trending (`'HIGH_VOLATILITY'`, `'TRENDING_BULLISH'`, `'TRENDING_BEARISH'`)**:
   * Avoid posting maker orders (adverse selection risk).
   * Route directly to CLOB Taker mode.
   * Submit immediate-or-cancel market orders to secure the price.

### Step C: Sizing & Caps Verification
1. Extract optimal size from Kelly calculations.
2. Apply the following strict mathematical caps in the risk engine:
   * **Concentration Cap**: No single position can exceed 20% of total capital.
   * **Drawdown Cap**: Scale down sizes proportionally if the portfolio drawdown exceeds 5%.

### Step D: Ledger Reserve Commit
1. Verify available capital in the database.
2. Write a ledger reserve record using `validate_and_reserve`.
3. Commit trade execution details to the positions table, storing the correct `tenant_wallet` to maintain isolation.

---

## 4. Behavioral Boundaries & Constraints
* > [!IMPORTANT]
  > **Execution Mode Safety**: If `MODE` is set to `PAPER` or `SHADOW`, the execution path must **never** make calls to a live trading wallet. It must record the trades strictly in the local paper ledger.
* > [!WARNING]
  > **Adverse Selection Protection**: Never post resting limit orders in high-volatility environments. Doing so risks having the order filled right before a major price trend moves against it.
* > [!CAUTION]
  > **Zero Size Drop**: Skip execution immediately if the risk engine calculates a target position size of 0.0, avoiding unnecessary gas fees or database locks.
