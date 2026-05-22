# 🦾 OpenClaw Integration & Compatibility Guide

This guide details how to integrate the **Lobstar Quant Agentic OS** with **OpenClaw**, the state-of-the-art, open-source, self-hosted AI gateway and autonomous agent platform. By aligning our modular skills with the OpenClaw directory structures, you can run Lobstar 24/7 on your local hardware/VPS and pilot it seamlessly through omnichannel messaging (Telegram, WhatsApp, Slack, Discord, Signal).

## Context7 Policy

Context7 (`https://github.com/upstash/context7`) is a documentation-only rule for all AI assistants used in this project, including Gemini, Copilot, OpenCode, and Codex.

- Use Context7 before relying on any external API, SDK, or setup/configuration detail.
- Do not treat Context7 as a runtime dependency.
- The authoritative local instructions are [`CLAUDE.md`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/CLAUDE.md) and [`.cursorrules`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/.cursorrules).

---

## 🏗️ 1. OpenClaw Skill Structure Compliance

OpenClaw packages agent capabilities as modular, self-contained **Skills**. Each skill is represented as a directory containing a `SKILL.md` file featuring a standardized YAML frontmatter schema.

### 📄 Skill Directory Layout Example
To expose Lobstar capabilities directly as OpenClaw skills, organize them as follows:
```
~/.openclaw/skills/
└── lobstar_market_intelligence/
    ├── SKILL.md
    └── lobstar_runner.py
```

### 📝 OpenClaw `SKILL.md` Standard Template
Here is the official compliant template for a Lobstar prediction-market scanning skill:

```markdown
---
name: "Lobstar Prediction Market Scanner"
description: "Monitors Polymarket Gamma events, HMM regimes, and executes Platt-calibrated sentiment analyses."
version: "2.0.0"
author: "Antigravity Team"
requirements:
  os:
    - linux
    - darwin
  python: ">=3.10"
  env:
    - VAULT_TOKEN
    - OPENROUTER_API_KEY
    - MODE
---

# 📡 Lobstar Market Scanner Skill

## Purpose
Enables the self-hosted OpenClaw gateway to query active Polymarket sentiment horizons, filter out thin liquidity, and output HMM-regimed volatility contexts.

## Usage Commands
* `/btc5` — BTC 5-minute sentiment horizon.
* `/eth15` — ETH 15-minute sentiment horizon.
* `/r` — Hidden Markov Model (HMM) regime report.
```

---

## ⚙️ 2. Hot-Reload Gateway Configuration (`openclaw.json`)

OpenClaw is governed by a central JSON5 configuration file located at `~/.openclaw/openclaw.json`. The OpenClaw Gateway automatically monitors this file and applies hot-reloaded adjustments without requiring a daemon restart.

### 📝 Compliant `openclaw.json` Integration Blueprint
To route messaging platforms, model providers, and local skills through the self-hosted gateway, merge the following parameters into your `openclaw.json`:

```json
{
  "$schema": "https://openclaw.ai/schema/v1/openclaw.schema.json",
  "gateway": {
    "host": "127.0.0.1",
    "port": 18789,
    "web_ui": true,
    "hot_reload": true
  },
  "providers": {
    "openrouter": {
      "api_key": "${ENV.OPENROUTER_API_KEY}",
      "default_model": "anthropic/claude-3.5-sonnet:beta"
    }
  },
  "channels": {
    "telegram": {
      "enabled": true,
      "bot_token": "${ENV.TELEGRAM_BOT_TOKEN}",
      "allowed_chats": ["${ENV.ALLOWED_CHAT_IDS}"]
    },
    "discord": {
      "enabled": false,
      "bot_token": ""
    }
  },
  "skills": {
    "directories": [
      "/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/.agents",
      "~/.openclaw/skills"
    ],
    "auto_approve": false,
    "security_level": "strict"
  }
}
```

---

## 🛡️ 3. Privilege Isolation & Execution Guardrails

When routing AI commands through the OpenClaw gateway, the **entropy key shield** and **multi-tenant RBAC** layers we implemented in Lobstar serve as essential firewalls:

1. **Gatekeep Input Injection**: The entropy shield in [prompt_memory.py](file:///home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/prompt_memory.py) checks all gateway observations. If the LLM generates or handles high-entropy hex strings (keys/tokens), they are instantly redacted before passing back to the channel.
2. **Access Control Routing**: When a command is triggered via a Discord/Telegram/Slack message, the `AccessControlManager` verifies the sender's whitelisted status and dynamically isolates their database commits (`tenant_wallet`) to prevent tenant crossover.
3. **Mode Verification**: Execution is forced into `PAPER` or `SHADOW` modes unless `MODE=PROD` is explicitly confirmed inside the OpenClaw configuration environment block.
