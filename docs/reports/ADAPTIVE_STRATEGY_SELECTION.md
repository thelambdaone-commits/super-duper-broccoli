# Adaptive Strategy Selection

Updated: 2026-05-20

## Objective

The autonomous selector chooses the best Polymarket opportunities by maximizing focused EV quality:

`score = ((EV / uncertainty) * liquidity_factor / cost - penalties) / time_to_settlement^gamma`

The selected signals still pass through:

- strategy lifecycle gates,
- autonomous mode controller,
- ledger,
- deterministic PortfolioRiskEngine,
- execution safeguards.

## Components

| Component | Role |
| --- | --- |
| `StrategySelector` | Ranks and selects top-k signals by EV/risk/cost/time. |
| `StrategyBandit` | Lightweight Thompson-style online learner per strategy arm. |
| `AutonomousTradingLoop` | Uses selector before opening positions. |
| `StrategyLifecycleManager` | Controls whether a strategy may emit actionable signals. |

## Strict Entry Gates

The selector rejects noisy opportunities before sizing:

- `EV >= ev_min`.
- `sigma_relative <= sigma_relative_max`.
- bid/ask depth converted to USDC must exceed `min_liquidity_usdc`.
- spread + fee/slippage estimate must stay below `max_cost`.
- time-to-settlement must stay inside configured min/max bounds.
- market orders are rejected unless EV is materially stronger than the minimum.

## Budget Controls

- concurrent markets are capped by `max_concurrent_markets`.
- new positions per cycle are capped by `max_new_positions_per_cycle`.
- market exposure is capped by `max_capital_per_market_pct`.
- suggested capital uses Kelly shrinkage and an absolute cap.
- correlated signals share a correlation group, so only the best one is selected.

## Inputs

Each strategy emits `StrategySignal`. The selector enriches it using:

- estimated probability,
- strategy edge,
- spread/slippage cost,
- probability variance,
- time to settlement,
- current exposure by market,
- bandit posterior performance.

## Feedback Loop

When an autonomous paper position closes, the loop updates the bandit with:

- realized PnL,
- slippage,
- fill status.

Positive PnL improves the posterior; negative/slippage-heavy outcomes penalize the arm.

## Safety

- Default selector is conservative: only positive final scores pass.
- Exploration is bounded by `exploration_rate`.
- Top-k limits prevent opening every possible strategy signal.
- Manipulative tactics remain excluded.
