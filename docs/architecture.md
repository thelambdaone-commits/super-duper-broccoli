# Project Architecture

## Global Workflow

```mermaid
sequenceDiagram
    participant T as Telegram
    participant P as Parser
    participant G as Predictive Gate
    participant R as Risk Engine
    participant E as Executor
    participant C as CLOB

    T->>P: New Signal (@sol BUY 0.50)
    P->>G: Market Data + Signal
    G->>G: Ensemble Forecast (Hybrid + TimesFM)
    G->>R: Probability + Confidence
    R->>R: Kelly Sizing + Regime Check
    R-->>E: Approval + Target Size
    E->>C: Maker Order (Post-Only)
    C-->>E: Order Live
    E->>T: Success Notification (OrderID)
```

## Modular Components

### 1. Predictive Matrix
The `PolymarketPredictiveEngine` combines:
- **XGBoost/LightGBM/RF** for tabular feature extraction.
- **TimesFM** for zero-shot trend analysis.
- **Isotonic Calibration** for Brier score optimization.

### 2. Risk Layer
The `PortfolioRiskEngine` enforces:
- **Net Beta Exposure** limits across all positions.
- **Correlated Drawdown** protections.
- **HMM-Based Regime Filtering** (Multiplier reduction in erratic markets).

### 3. Execution Engine
The `PassiveExecutor` manages:
- **Maker-First Logic**: Minimizing slippage and fees.
- **Dynamic Replacements**: Updating price/size as orderbook moves.
- **Taker Fallback**: Ensuring fills if trade objective is critical.
