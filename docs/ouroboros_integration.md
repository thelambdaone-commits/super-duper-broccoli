# Ouroboros Integration

## Requirements
- Python >= 3.12 (currently using 3.11)
- Install: `pip install ouroboros-ai`

## What is Ouroboros?

**Agent OS** - Stop prompting. Start specifying.

Ouroboros provides a structured specification-first workflow for AI coding:

1. **Interview** - Socratic questioning to expose hidden assumptions
2. **Seed** - Crystallize into immutable specification
3. **Execute** - Double Diamond decomposition
4. **Evaluate** - 3-stage verification (Mechanical -> Semantic -> Consensus)
5. **Evolve** - Evolutionary loop until ontology convergence (>= 0.95 similarity)

## Integration with Lobstar

Ouroboros can enhance the swarm agents with:
- Ambiguity scoring for signal validation (<= 0.2 threshold)
- Specification-first development for new agents
- 3-stage evaluation for trade decisions
- Ontology convergence for model drift detection

## Quick Start (when Python >= 3.12)

```bash
# Install Ouroboros
pip install ouroboros-ai

# Setup runtime
ouroboros setup --runtime claude

# Inside Claude Code session:
ooo interview "Build a new arbitrage detection agent"
ooo run seed.yaml
```

## Commands

| Command | Description |
|---------|-------------|
| `ooo interview` | Socratic questioning to define requirements |
| `ooo seed` | Generate immutable specification |
| `ooo run` | Execute via Double Diamond |
| `ooo evaluate` | 3-stage verification |
| `ooo evolve` | Evolutionary loop until convergence |
| `ooo ralph` | Persistent loop until verified |

## Nine Minds

Ouroboros provides 9 specialized agents:

1. **Socratic Interviewer** - Questions only, exposes assumptions
2. **Ontologist** - Finds essence, not symptoms  
3. **Seed Architect** - Crystallizes specs
4. **Evaluator** - 3-stage verification
5. **Contrarian** - Challenges every assumption
6. **Hacker** - Finds unconventional paths
7. **Simplifier** - Removes complexity
8. **Researcher** - Stops coding, investigates
9. **Architect** - Identifies structural causes

## Future Integration

When Python is upgraded to 3.12+, integrate with:

```python
# In continuous_improvement/agents/
from ouroboros import OuroborosEngine

# Use for:
# - New agent specification
# - Trade decision validation
# - Drift detection convergence
# - Specification-first agent development
```

## Reference
- GitHub: https://github.com/Q00/ouroboros
- PyPI: https://pypi.org/project/ouroboros-ai/