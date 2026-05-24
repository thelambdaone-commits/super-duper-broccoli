# GSD Execution Skill

## 1. Purpose
Adapt GSD-style context engineering and spec-driven development to Lobstar without importing an external runtime. The goal is to keep work packets small, explicit, testable, and safe for a trading system.

## 2. Trigger Conditions
Use this skill when:

- A task spans multiple files or domains.
- The user asks to adapt an external project, framework, or agent methodology.
- Context size is growing and the work needs a compact handoff.
- A change requires proof through tests, docs, or operational checks.

## 3. Execution Steps

### Step A: Intake
1. Restate the concrete goal in one sentence.
2. Define scope and non-goals.
3. Select the specialist from `config/ai_specialists.json`.
4. Build or mentally follow a `GSDWorkflow` task packet.

### Step B: Context Budget
1. Read `config/project_contexts.json` before broad file exploration.
2. Load only priority files and targeted references.
3. Summarize external projects instead of vendoring or dumping them into prompts.

### Step C: Bounded Implementation
1. Prefer adapters, config files, skills, tests, and docs.
2. Avoid replacing trading execution, ledger, risk, or secret flows with external framework behavior.
3. Keep every changed file tied to the task packet.

### Step D: Verification
1. Run focused tests for changed behavior.
2. Validate JSON/YAML/config files after editing.
3. Record residual risk when a live network or production check cannot be run.

### Step E: Handoff
1. State changed files and behavior.
2. Report tests run and exact outcomes.
3. Provide the next command only if it is operationally useful.

## 4. Behavioral Boundaries & Constraints
* Do not send secrets, private keys, Telegram messages, wallet encrypted data, or raw logs to external LLMs.
* Do not execute live trades from a generated plan.
* Do not vendor upstream GSD code into this repo without a separate license and dependency review.
* Do not bypass `MODE`, risk sizing, ledger reserve, HMM regime, or Polymarket credential guardrails.
