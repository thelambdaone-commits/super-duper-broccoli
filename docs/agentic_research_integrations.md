# Agentic Research Integrations

This project uses external agentic research as design input, not as vendored runtime code.

## TradingAgents-Inspired Desk

`config/trading_agents_playbook.json` defines a trading-firm style decision flow:

- Analyst team builds market context and data-quality flags.
- Research debate requires both bull and bear cases.
- Trader synthesis proposes a bounded paper-first order plan.
- Risk management enforces circuit breaker, ledger reserve, and mode gates.
- Execution handoff remains deterministic; LLM outputs never place orders directly.

The playbook is intended for prompt routing, trace validation, and future MCP exposure.

## Unity ML-Agents-Inspired Training

`config/rl_training_blueprint.json` maps the current market simulator needs into an RL environment contract:

- Observations: spread, liquidity, regime, exposure, ledger capital, slippage.
- Actions: hold, passive quote, taker trade, cancel, reduce exposure.
- Rewards: realized PnL and risk-adjusted return minus drawdown, stale data, slippage, and risk violations.
- Promotion gates: walk-forward results, drawdown limits, calibration improvement, trust-layer trace pass.

This is a blueprint for paper/replay training. It must not promote a policy into production without deterministic risk and ledger gates.

## GitHub Trust-Layer Pattern

`core/services/agentic_trust_layer.py` implements structural validation for non-deterministic workflows.

Instead of requiring exact replay, it checks that essential milestones appear in order. Extra events such as retries, loading states, telemetry, or fallback queries are allowed.

Example essential trading trace:

```text
ingest_signal -> analyst_context_ready -> research_debate_completed -> trader_plan_created -> risk_gate_passed -> ledger_reserved -> execution_submitted -> post_trade_recorded
```

This catches serious failures such as skipping the risk gate or ledger reserve while tolerating harmless workflow variation.

## Source References

- TradingAgents: https://github.com/TauricResearch/TradingAgents
- Unity ML-Agents: https://github.com/Unity-Technologies/ml-agents
- GitHub AI and ML: https://github.blog/ai-and-ml/
- Agentic validation article: https://github.blog/ai-and-ml/generative-ai/validating-agentic-behavior-when-correct-isnt-deterministic/
