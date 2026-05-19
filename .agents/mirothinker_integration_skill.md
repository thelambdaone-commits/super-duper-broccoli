# MiroThinker Integration Skill

## Purpose
MiroThinker is a specialized framework for AI agents to reason, plan, and execute complex cognitive tasks. This skill integrates MiroThinker into Lobstar to enhance agent reasoning, multi-step planning, and decision-making processes.

## Triggers
- `/think plan` - Complex reasoning and planning
- `/think analyze` - Deep analysis with MiroThinker reasoning chain
- `/think decide` - Multi-criteria decision making
- `/agent mirothinker` - Direct MiroThinker invocation

## Integration Points
- **Location**: `agents/mirothinker/`
- **Type**: Multi-architecture (apps + libs monorepo)
- **Apps**: `agents/mirothinker/apps/`
- **Libs**: `agents/mirothinker/libs/`

## Execution Steps
1. Load MiroThinker environment from `agents/mirothinker/`
2. Initialize reasoning chain with problem context
3. Execute multi-step thinking process
4. Generate structured output with reasoning trace
5. Return results to Lobstar with confidence scores

## Behavioral Boundaries & Constraints
- **Transparent reasoning**: Show thinking chain to users
- **Confidence thresholds**: Only recommend decisions above 0.75 confidence
- **No autonomous actions**: All decisions require human approval
- **Resource limits**: Reasoning chains capped at 10 steps
- **Cost awareness**: Track API costs for reasoning operations

## Dependencies
- Rust toolchain (justfile build system)
- Python >= 3.10 (for integration with Lobstar)
- Required libs: See `agents/mirothinker/libs/`

## Configuration
```bash
# Initialize MiroThinker
cd agents/mirothinker
just setup  # Use justfile for setup

# Build all apps and libraries
just build
```

## Usage Examples
```python
# Import and use MiroThinker within Lobstar agents
from agents.mirothinker import MiroThinker

# Complex reasoning task
result = await MiroThinker.think({
    "problem": "Optimize trading strategy",
    "context": market_data,
    "constraints": risk_limits
})

# Multi-criteria decision
decision = await MiroThinker.decide({
    "options": candidate_strategies,
    "criteria": weighted_metrics,
    "threshold": 0.8
})
```

## Agent Memory Integration
- MiroThinker reasoning traces stored in `agents/mirothinker/memory/`
- Supports multi-agent collaboration with GitAgent
- Decision audit trail for compliance

## Best Practices
1. Use for complex market analysis and strategy decisions
2. Leverage reasoning chains for regulatory compliance
3. Store decision traces for post-trade analysis
4. Combine with GitAgent for code-driven decisions
