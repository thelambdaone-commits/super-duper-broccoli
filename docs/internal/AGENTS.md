# 🤖 LOBSTAR QUANT AGENTIC OS — AGENTS GUIDE

Welcome to the agent specialist configuration and coordination framework for the Lobstar Quant Agentic OS. This document outlines the active AI specialists, their priority files, and the Moltbook-inspired modular skills that dictate their behaviors and constraints.

---

## 🏗️ Specialist Architecture

Lobstar OS partitions cognitive responsibilities across specialized AI agents. This guarantees high focus, reduces prompt tokens, and prevents complex multi-agent cross-contamination.

| Specialist ID | Name | Role | Priority Entrypoints | Skill Prompt File |
|---|---|---|---|---|
| `security` | Security Specialist | Cryptographic secrets, Vault/Ledger access, command guarding, RBAC, tenant isolation. | [vault_handler.py](file:///home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/vault_handler.py), [access_control.py](file:///home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/access_control.py) | [.agents/security_rbac_skill.md](file:///home/ogj9f33gvvzc/quant-agentic-trading-core-v2/.agents/security_rbac_skill.md) |
| `trading` | Trading Specialist | Ingestion pipelines, predictive opinion generation, market HMM regiming, Polymarket/Gamma scanning, VCP/CANSLIM screeners. | [signal_generator.py](file:///home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/signal_generator.py), [crypto_market_intelligence.py](file:///home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/crypto_market_intelligence.py), [market_discovery.py](file:///home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/market_discovery.py), [screeners.py](file:///home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/screeners.py) | [.agents/market_intelligence_skill.md](file:///home/ogj9f33gvvzc/quant-agentic-trading-core-v2/.agents/market_intelligence_skill.md) |
| `execution` | Execution Specialist | Adaptive strategy routing, Low-Vol Maker/Passive, High-Vol CLOB Taker, Arbitrage Netting. | [passive_executor.py](file:///home/ogj9f33gvvzc/quant-agentic-trading-core-v2/execution/passive_executor.py), [main_agentic_clob.py](file:///home/ogj9f33gvvzc/quant-agentic-trading-core-v2/main_agentic_clob.py) | [.agents/adaptive_execution_skill.md](file:///home/ogj9f33gvvzc/quant-agentic-trading-core-v2/.agents/adaptive_execution_skill.md) |
| `credential` | Polymarket Credential Specialist | CLOB credential loading, encrypted wallet resolution, proxy wallet linking, balance checking, order placement pipeline. | [vault_handler.py](file:///home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/vault_handler.py), [credential_manager.py](file:///home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/credential_manager.py), [container.py](file:///home/ogj9f33gvvzc/quant-agentic-trading-core-v2/core/container.py) | [.agents/polymarket_credential_flow_skill.md](file:///home/ogj9f33gvvzc/quant-agentic-trading-core-v2/.agents/polymarket_credential_flow_skill.md) |
| `tuning` | ML Confidence Tuner | Closed simulated trade outcome resolution, reinforcement autotuning, ML bias mapping. | [rl_feedback_loop.py](file:///home/ogj9f33gvvzc/quant-agentic-trading-core-v2/scripts/rl_feedback_loop.py) | [.agents/reinforcement_learning_skill.md](file:///home/ogj9f33gvvzc/quant-agentic-trading-core-v2/.agents/reinforcement_learning_skill.md) |
| `gsd` | GSD Workflow Operator | Spec intake, context budgeting, phase gates, verification reports, durable handoff notes. | [gsd_workflow.py](file:///home/ogj9f33gvvzc/quant-agentic-trading-core-v2/core/services/gsd_workflow.py), [gsd_operating_system.json](file:///home/ogj9f33gvvzc/quant-agentic-trading-core-v2/config/gsd_operating_system.json) | [.agents/gsd_execution_skill.md](file:///home/ogj9f33gvvzc/quant-agentic-trading-core-v2/.agents/gsd_execution_skill.md) |
| `gitagent` | GitAgent Specialist | Automated Git workflows, PR management, code review, branch analysis, commit history insights. | [agents/gitagent/](file:///home/ogj9f33gvvzc/quant-agentic-trading-core-v2/agents/gitagent/), [agents/gitagent/skills/](file:///home/ogj9f33gvvzc/quant-agentic-trading-core-v2/agents/gitagent/skills/) | [.agents/gitagent_integration_skill.md](file:///home/ogj9f33gvvzc/quant-agentic-trading-core-v2/.agents/gitagent_integration_skill.md) |
| `mirothinker` | MiroThinker Reasoning Agent | Complex reasoning, multi-step planning, decision analysis, confidence scoring, transparent thinking chains. | [agents/mirothinker/](file:///home/ogj9f33gvvzc/quant-agentic-trading-core-v2/agents/mirothinker/), [agents/mirothinker/apps/](file:///home/ogj9f33gvvzc/quant-agentic-trading-core-v2/agents/mirothinker/apps/) | [.agents/mirothinker_integration_skill.md](file:///home/ogj9f33gvvzc/quant-agentic-trading-core-v2/.agents/mirothinker_integration_skill.md) |

---

## 🗂️ Moltbook Skill Directory Layout

Individual skills are maintained in human-readable Markdown format within the [.agents/](file:///home/ogj9f33gvvzc/quant-agentic-trading-core-v2/.agents/) directory. This enables on-demand prompt injection and strict compliance auditing.

### Skill File Composition Pattern
Each Markdown skill file conforms to the following standardized structure:
1. **Purpose**: High-level goal and operational context.
2. **Triggers**: Explicit events or commands that activate this skill.
3. **Execution Steps**: Detailed step-by-step logic the agent must run.
4. **Behavioral Boundaries & Constraints**: What the agent is strictly forbidden from doing (e.g. security caps, secret exfiltration rules).

---

## 🛡️ Bounded Execution & Risk Guardrails

AI specialist suggestions are **never** executed directly without passing deterministic validation layers.
* **HMM Regime Guard**: Trading is restricted or scaled based on HMM volatility classifications.
* **Risk Sizing**: Kelly calculations, concentration caps, and drawdown caps are calculated mathematically in [portfolio_risk_engine.py](file:///home/ogj9f33gvvzc/quant-agentic-trading-core-v2/core/portfolio_risk_engine.py).
* **Ledger Reserve Rules**: The database must authorize and reserve capital in [ledger_db.py](file:///home/ogj9f33gvvzc/quant-agentic-trading-core-v2/ledger/ledger_db.py) before trades are executed.
* **Execution Guard**: Production orders require explicit environment confirmation (`MODE=PRD`).

---

## 📚 External Skill References

The LOBSTAR ecosystem integrates best practices and skills from the following repositories:

### Core Trading Skills
| Repository | Description | Integration |
|---|---|---|
| [tradermonty/claude-trading-skills](https://github.com/tradermonty/claude-trading-skills) | Market breadth, VCP/CANSLIM, position sizing, trader memory | ✅ Integrated in [screeners.py](file:///home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/screeners.py) |
| [alirezarezvani/claude-skills](https://github.com/alirezarezvani/claude-skills) | 263+ skills for engineering, marketing, product, compliance | 📋 Reference |

### System Prompts & Best Practices
| Repository | Description | Integration |
|---|---|---|
| [affaan-m/everything-claude-code](https://github.com/affaan-m/everything-claude-code) | Comprehensive Claude Code resources | 📋 Reference |
| [x1xhlol/system-prompts-and-models-of-ai-tools](https://github.com/x1xhlol/system-prompts-and-models-of-ai-tools) | System prompts for AI tools | 📋 Reference |
| [gsd-build/get-shit-done](https://github.com/gsd-build/get-shit-done) | Spec-driven, context-engineered workflow adapted locally through `config/gsd_operating_system.json`, `.agents/gsd_execution_skill.md`, and `core/services/gsd_workflow.py` | ✅ Integrated |
| [garrytan/gstack](https://github.com/garrytan/gstack) | AI agent infrastructure | 📋 Reference |
| [shareAI-lab/learn-claude-code](https://github.com/shareAI-lab/learn-claude-code) | Learning resources for Claude Code | 📋 Reference |
| [hesreallyhim/awesome-claude-code](https://github.com/hesreallyhim/awesome-claude-code) | Curated Claude Code resources | 📋 Reference |
| [davila7/claude-code-templates](https://github.com/davila7/claude-code-templates) | Templates for Claude Code | 📋 Reference |
| [shanraisshan/claude-code-best-practice](https://github.com/shanraisshan/claude-code-best-practice) | Best practices | 📋 Reference |
| [VoltAgent/awesome-claude-code-subagents](https://github.com/VoltAgent/awesome-claude-code-subagents) | Sub-agents patterns | 📋 Reference |
| [Piebald-AI/claude-code-system-prompts](https://github.com/Piebald-AI/claude-code-system-prompts) | System prompts collection | 📋 Reference |
| [Q00/ouroboros](https://github.com/Q00/ouroboros) | Agent OS - specification-first AI coding workflow (requires Python 3.12+) | 📋 Reference |

### Integrated Agent Specialists (Submodules)
| Repository | Description | Integration | Location |
|---|---|---|---|
| [open-gitagent/gitagent](https://github.com/open-gitagent/gitagent) | Git automation, PR management, code review agent | ✅ **Git Submodule** | `agents/gitagent/` |
| [MiroMindAI/MiroThinker](https://github.com/MiroMindAI/MiroThinker) | Advanced reasoning engine for AI agents | ✅ **Git Submodule** | `agents/mirothinker/` |

---

## 🎯 Market Discovery Commands

| Command | Description |
|---|---|
| `/markets discover` | AI-scored market opportunities |
| `/markets opportunities` | Betting edges with spread > X% |
| `/markets contrarian` | Contrarian betting setups |
| `/markets vcp` | Volatility Contraction Pattern screener |
| `/markets canslim` | CANSLIM methodology screener |
