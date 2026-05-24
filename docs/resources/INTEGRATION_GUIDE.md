# 🚀 GitAgent & MiroThinker Integration Guide

This document outlines how to initialize and use the newly integrated **GitAgent** and **MiroThinker** specialists within the Lobstar Quant Agentic OS.

## 📋 Overview

| Agent | Purpose | Location | Status |
|---|---|---|---|
| **GitAgent** | Git workflow automation, PR management, code review | `agents/gitagent/` | ✅ Integrated (Git Submodule) |
| **MiroThinker** | Advanced reasoning, planning, decision analysis | `agents/mirothinker/` | ✅ Integrated (Git Submodule) |

---

## 🛠️ Setup Instructions

### 1. Initialize Submodules

After cloning or pulling the repository:

```bash
# Initialize and download submodules
git submodule update --init --recursive

# Or pull latest from each submodule
git submodule update --remote
```

### 2. GitAgent Setup

GitAgent is a TypeScript/Node.js agent for Git automation.

```bash
cd agents/gitagent

# Install dependencies
npm install

# Create environment configuration
cp .env.example .env

# Configure your GitHub credentials (edit .env with your token)
# GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
# GITHUB_API_URL=https://api.github.com

# Verify installation
npm run test
```

**Key Files:**
- `agents/gitagent/src/` — Main agent logic
- `agents/gitagent/skills/` — Skill modules (review, analyze, suggest)
- `agents/gitagent/agents/` — Agent configurations

### 3. MiroThinker Setup

MiroThinker is a Rust + Python monorepo for advanced reasoning.

```bash
cd agents/mirothinker

# Install build tools (requires Rust and just)
# If you don't have 'just' installed:
# curl --proto '=https' --tlsv1.2 -sSf https://just.systems/install.sh | bash

# Build all libraries and apps
just setup
just build

# Verify Python integration
python -c "import sys; sys.path.insert(0, '.'); print('MiroThinker available')"
```

**Key Files:**
- `agents/mirothinker/libs/` — Core reasoning libraries
- `agents/mirothinker/apps/` — CLI and application modules
- `agents/mirothinker/justfile` — Build configuration

---

## 🎯 Usage Examples

### GitAgent Commands

```python
# From within Lobstar agents/code
from agents.gitagent.src import GitAgent

# Perform code review on PR
result = await GitAgent.review({
    "repo": "origin",
    "pr": 42,
    "depth": "comprehensive"
})

# Analyze commit history
history = await GitAgent.analyze({
    "branch": "main",
    "depth": 10
})

# Get suggestions for improvement
suggestions = await GitAgent.suggest({
    "file": "src/trading/strategy.py",
    "context": "market_analysis"
})
```

### MiroThinker Reasoning

```python
# From within Lobstar agents/code
from agents.mirothinker.apps import MiroThinker

# Complex multi-step reasoning
analysis = await MiroThinker.think({
    "problem": "Optimize trading strategy under volatility",
    "context": {
        "market_data": prices,
        "portfolio": positions,
        "constraints": risk_limits
    },
    "steps": 5
})

# Structured decision making
decision = await MiroThinker.decide({
    "options": candidate_strategies,
    "criteria": {
        "sharpe_ratio": 0.4,
        "max_drawdown": 0.3,
        "volatility": 0.2
    },
    "confidence_threshold": 0.75
})

# Confidence-scored reasoning
ranked = await MiroThinker.rank({
    "candidates": market_opportunities,
    "ranking_criteria": edge_metrics,
    "return_confidence": True
})
```

---

## 🔌 Integration Points

### Lobstar Specialist Routing

Both agents are configured in the **Specialist Architecture** (see `AGENTS.md`):

| Specialist | Trigger | Skill File |
|---|---|---|
| `gitagent` | `/git review`, `/git analyze` | `.agents/gitagent_integration_skill.md` |
| `mirothinker` | `/think plan`, `/think decide` | `.agents/mirothinker_integration_skill.md` |

### Adding to Your Agent Workflow

```python
# In any Lobstar agent (e.g., trading specialist)
from core.agent_router import route_to_specialist

# Route to GitAgent for code review
review_result = await route_to_specialist(
    specialist="gitagent",
    action="review",
    params={"pr": 42}
)

# Route to MiroThinker for reasoning
decision = await route_to_specialist(
    specialist="mirothinker",
    action="think",
    params={"problem": "Strategy optimization"}
)
```

---

## 📚 Skill Configuration

### GitAgent Skills (Moltbook)

See `.agents/gitagent_integration_skill.md` for:
- **Triggers**: Events that activate GitAgent
- **Execution Steps**: Workflow logic
- **Behavioral Boundaries**: Security constraints (no force-pushes, branch protection)
- **Dependencies**: Node.js >= 18, Git >= 2.30

### MiroThinker Skills (Moltbook)

See `.agents/mirothinker_integration_skill.md` for:
- **Triggers**: Commands that activate reasoning
- **Execution Steps**: Thinking chain workflow
- **Behavioral Boundaries**: Confidence thresholds, resource limits
- **Dependencies**: Rust toolchain, Python >= 3.10

---

## 🧪 Testing Integration

### Unit Tests

```bash
# Test GitAgent
cd agents/gitagent
npm run test

# Test MiroThinker
cd agents/mirothinker
just test
```

### Integration Tests (from Lobstar root)

```bash
# Run pytest with agent discovery
pytest tests/ -k "gitagent or mirothinker" -v
```

### Manual Verification

```bash
# Check submodule status
git submodule status

# Verify GitAgent is accessible
node -e "console.log(require('./agents/gitagent/package.json').name)"

# Verify MiroThinker libs
ls agents/mirothinker/libs/
```

---

## 🔄 Updating Submodules

To pull latest changes from both agent repositories:

```bash
# Update all submodules to latest
git submodule update --remote

# Or update specific submodule
git submodule update --remote agents/gitagent
git submodule update --remote agents/mirothinker

# Commit the pin
git add agents/gitagent agents/mirothinker
git commit -m "chore: bump GitAgent and MiroThinker submodules"
```

---

## ⚠️ Troubleshooting

### Submodules not initialized

```bash
# Full reset and re-init
git submodule deinit -f agents/gitagent agents/mirothinker
rm -rf .git/modules/agents/
git submodule update --init --recursive
```

### GitAgent npm issues

```bash
# Clear npm cache and reinstall
cd agents/gitagent
rm -rf node_modules package-lock.json
npm install
```

### MiroThinker Rust build issues

```bash
# Ensure Rust is up-to-date
rustup update

# Rebuild from scratch
cd agents/mirothinker
just clean
just build
```

---

## 📖 Documentation

- **GitAgent**: See `agents/gitagent/Documentation.md`
- **MiroThinker**: See `agents/mirothinker/README.md`
- **Lobstar Agents**: See `AGENTS.md`

---

## 🎓 Next Steps

1. **Initialize submodules** → `git submodule update --init --recursive`
2. **Setup GitAgent** → Follow GitAgent Setup (step 2 above)
3. **Setup MiroThinker** → Follow MiroThinker Setup (step 3 above)
4. **Test integration** → Run unit tests
5. **Add to workflows** → Use agent routing in your specialists

Enjoy the enhanced reasoning and Git automation! 🚀
