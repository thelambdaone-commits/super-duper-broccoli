# Ouroboros Integration

This repository contains a lightweight compatibility layer for Ouroboros Agent OS.
The current code does not implement the full Ouroboros workflow; it exposes a
small wrapper that reports availability and returns explicit `not_implemented`
responses when the package is not present.

## Current Status

- Runtime requirement: Python `>= 3.12` for the external `ouroboros` package.
- Local wrapper: [`utils/ouroboros_integration.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/ouroboros_integration.py)
- Behavior today:
  - `OuroborosIntegration.is_available()` reports whether `import ouroboros` succeeds.
  - `get_status()` returns a small status map with the Python version requirement.
  - `interview_agent_requirements()` returns `unavailable` or `not_implemented`.
  - `validate_trade_decision()` returns `unavailable` or `not_implemented`.

## What It Is For

The intended use is to keep a narrow integration point ready for future
specification-first workflows without making the trading runtime depend on
Ouroboros being installed.

Practical uses:

- Agent requirement clarification before adding new autonomous behaviors
- Structured validation hooks for trade decision review
- Future drift-analysis workflows if the project adopts Ouroboros natively

## What It Is Not

- It is not a production dependency of the current runtime.
- It does not expose the full Ouroboros CLI workflow.
- It does not perform interview, seed, evaluation, or evolution steps locally.

## Code Contract

```python
from utils.ouroboros_integration import get_ouroboros_integration

integration = get_ouroboros_integration()
status = integration.get_status()
available = integration.is_available()
```

Expected responses:

- When Ouroboros is missing: `{"status": "unavailable", "message": "Requires Python >= 3.12"}`
- When Ouroboros is present: `{"status": "not_implemented", "message": "Implement when Ouroboros available"}`

## Deployment Notes

- Keep the wrapper import-safe even when Ouroboros is absent.
- Do not make production trade execution depend on this module.
- Use it as an integration seam, not as a hidden runtime assumption.

## References

- Local module: [`utils/ouroboros_integration.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/ouroboros_integration.py)
- Project context: [`AGENTS.md`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/AGENTS.md)
- Upstream project: https://github.com/Q00/ouroboros
