# 🔐 Security & RBAC Skill

*Moltbook-inspired Agentic Skill Document for role-based access control, cryptographic key isolation, and multi-tenant DB segregation.*

---

## 1. Purpose
Enforces institutional-grade access control, cryptographic key protection, and strict tenant isolation on all database and dashboard interactions, ensuring no non-admin user can read capital metrics or leak trading history.

---

## 2. Trigger Conditions
* **Incoming Telegram Updates**: Any message or command execution containing administrative queries.
* **Callback Queries**: Interactions on dashboard inline steering buttons (e.g. balance requests, wallet details).
* **Ledger Updates**: Recording new orders or updating capital allocations in the SQLite database.

---

## 3. Execution Steps

### Step A: Authorization Check
1. Retrieve the incoming message/callback query `chat_id`.
2. Inspect the whitelist maintained by the `AccessControlManager`.
3. If the user is **not** an administrator:
   * Stop processing immediately.
   * Log an audit warning: `🚨 [SECURITY WARNING: Unauthorized Admin Query Attempt] Chat ID: <chat_id>`.
   * Return a polite, generic rejection: `Unauthorized.`.

### Step B: Multi-Tenant Tenant Isolation
1. For every transaction (position, order, balance query), retrieve the assigned wallet address using `obtenir_wallet_associe(chat_id)`.
2. If the `chat_id` is unregistered, route strictly to the isolated fallback string format `DEFAULT_ISOLATED_WALLET_{chat_id}` to prevent cross-tenant data leaks.
3. Write/read SQLite tables (`positions`, `paper_positions`) using the assigned `tenant_wallet` column as a strict query constraint.

### Step C: Secrets & Vault Ingestion
1. Retrieve blockchain keys, API tokens, and credentials strictly via the `VaultHandler` database.
2. Read the local token securely from `~/.vault-token`.
3. Redact all secret values automatically inside `prompt_memory.py` using FTS regex patterns before appending context to LLM opinion prompts.

---

## 4. Behavioral Boundaries & Constraints
* > [!IMPORTANT]
  > **Multi-Tenant Isolation**: No tenant's signal or execution data must ever spill over to another tenant. Query filters in SQL must always include the `tenant_wallet` constraint.
* > [!WARNING]
  > **No Secret Logging**: Never log passwords, API keys, private keys, or Vault tokens. Any output strings containing these patterns must be immediately redacted.
* > [!CAUTION]
  > **Audit Warning Formatting**: Unauthorized administrative attempts must log the warning in the exact format `🚨 [SECURITY WARNING: Unauthorized Admin Query Attempt]` to ensure monitors trigger security alerts.
