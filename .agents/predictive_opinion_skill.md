# 🧠 Predictive Opinion Skill

*Moltbook-inspired Agentic Skill Document for autonomous double-turn local tool-use and LLM opinion loops.*

---

## 1. Purpose
Guides the agent through executing high-fidelity, cost-aware double-turn local tool-use interactions with the local LLM (Claude 3.5 Sonnet on OpenRouter). It allows the model to query internal systems (ledger, regimes) locally and output a deterministic, structured JSON opinion.

---

## 2. Trigger Conditions
* **Signal Ingestion**: A new raw trading signal is parsed and validated.
* **Periodic Evaluation**: Background task queries a local opinion for active portfolio rebalancing.

---

## 3. Execution Steps

### Step A: System Context Generation
1. Fetch current project memories and latest decisions using `build_project_prompt_context`.
2. Construct a strict system prompt instructing the model to behave as a **Lead Quant Analyst**.
3. Expose local tool function schemas:
   * `get_ledger_state`: Queries the local SQLite DB for allocations and reserves.
   * `get_market_regime`: Queries current HMM state and volatility metrics.

### Step B: The First Inference Turn (Tool Call Detection)
1. Send the compiled context, tools, and the target question to OpenRouter.
2. Read the response. If the LLM returns `tool_calls`:
   * Parse the requested tool name and arguments.
   * Intercept and execute the query **locally** using safe, deterministic local Python code.
   * Format the execution results as a tool message.

### Step C: The Second Inference Turn (Opinion Capture)
1. Append the tool results message to the conversation history.
2. Call the OpenRouter API a second time with the complete tool execution context.
3. Force a structured JSON output matching the target schema:
   ```json
   {
     "action": "BUY | SELL | HOLD",
     "confidence": 0.0,
     "rationale": "...",
     "stop_loss": 0.0
   }
   ```

### Step D: Validation & Sanitization
1. Sanitize the output string to strip any markdown wrappers (` ```json `).
2. Validate the JSON syntax. If parsing fails, trigger the local fallback opinion model (HMM/Kelly consensus).

---

## 4. Behavioral Boundaries & Constraints
* > [!IMPORTANT]
  > **Strict Tool Bounds**: The LLM is strictly allowed to read state via defined tools. It must **never** be given tools that write code, delete files, or execute raw shell commands.
* > [!WARNING]
  > **Token Optimization**: Keep system context under 2,500 tokens. Compact all observations and summaries before prompt construction to preserve context window.
* > [!CAUTION]
  > **Key Guarding**: OpenRouter keys must always be retrieved securely from the Vault (`VaultHandler`). They must never be printed to stdout, logged to files, or returned in Telegram reports.
