# 🎯 Reinforcement Learning Skill

*Moltbook-inspired Agentic Skill Document for simulated trade outcome resolution and ML confidence autotuning.*

---

## 1. Purpose
Guides the agent through resolving simulated trade outcomes (wins vs losses), updating the machine learning confidence biases for core assets (BTC, ETH, SOL), and dynamically adjusting ML weights to prevent cognitive overfitting.

---

## 2. Trigger Conditions
* **Hourly Maintenance Cycle**: Background executor runs the autotuning pipeline.
* **Manual Trigger**: Executing `scripts/rl_feedback_loop.py` or `/r` regime check.

---

## 3. Execution Steps

### Step A: Closed Trade Scanning
1. Query the ledger database for any newly closed simulated paper positions.
2. If no new positions are found, exit gracefully without altering weights.

### Step B: Win/Loss Resolution
1. Analyze the profit and loss (PnL) of each resolved paper trade.
2. Classify outcomes:
   * **Win (P&L > 0)**: Increment the asset's confidence bias by **+0.05**.
   * **Loss (P&L < 0)**: Decrement the asset's confidence bias by **-0.08**.

### Step C: Weight Capping & Scaling
1. Retrieve historical weights from `data/ml_weights.json`.
2. Apply the updated adjustments to the corresponding ticker.
3. Enforce strict mathematical bounding caps to prevent runaways:
   * **Minimum Bias**: `0.1x` (never fully disable an asset's scanning capacity).
   * **Maximum Bias**: `5.0x` (never let a hot streak over-concentrate the agent).

### Step D: Saving & Prompt Ingestion
1. Write the updated dynamic weights to `data/ml_weights.json`.
2. Ensure the next training run (`train_all.py`) and HMM predictive scanner imports the adjusted dynamic weights, prioritizing high-alpha signals.

---

## 4. Behavioral Boundaries & Constraints
* > [!IMPORTANT]
  > **Asymmetry Protection**: The adjustment logic uses an asymmetric penalty: losses are penalized more heavily (-0.08) than wins are rewarded (+0.05), protecting the portfolio from local streak biases.
* > [!WARNING]
  > **Data Safety**: Dynamic weights must be stored locally under `data/ml_weights.json`. Never send the raw weights file to external LLM providers.
* > [!CAUTION]
  > **Zero Division Guard**: If an asset's weight drops near zero, it must be capped at the minimum bounds `0.1x` to avoid division or calculation errors in the Kelly sizing engine.
