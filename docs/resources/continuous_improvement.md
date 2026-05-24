# Continuous Improvement

The repository includes a small self-analysis and improvement loop.

## CI Agent

[`continuous_improvement/agent.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/continuous_improvement/agent.py)
defines `CIRegistry`, which combines:

- code analysis
- knowledge-base logging
- test-gap reporting
- skill-based improvement suggestions

## Typical Uses

- generate a consolidated improvement report
- inspect a specific skill
- record a decision, error, or test run
- surface untested modules
- produce a quick summary of the internal knowledge base

## Important Commands

The command interface accepts:

- `analyze`
- `report`
- `gaps`
- `suggestions`
- `skills`
- `record-decision`
- `record-error`
- `record-test`
- `summary`

## Related Modules

- [`continuous_improvement/analyzer.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/continuous_improvement/analyzer.py)
- [`continuous_improvement/knowledge_base.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/continuous_improvement/knowledge_base.py)
- [`continuous_improvement/test_improver.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/continuous_improvement/test_improver.py)
