# OpenViking Integration Skill

## Purpose
OpenViking is an optional context database backend for compact agent memory, resource indexing, and search-backed retrieval. In Lobstar it should extend the prompt-context pipeline, not replace local deterministic controls.

## Triggers
- `/context openviking` - Build or inspect OpenViking-backed context
- `/memory search` - Search OpenViking for compact project context
- `/agent openviking` - Inspect OpenViking integration status

## Integration Points
- **Location**: `utils/openviking_adapter.py`
- **Prompt pipeline**: `utils/prompt_memory.py`
- **Project context**: `config/project_contexts.json`
- **Integration registry**: `config/agent_integrations.json`

## Execution Steps
1. Check `OPENVIKING_ENABLED` and local configuration.
2. Resolve the OpenViking base URL and auth headers.
3. Query the search endpoint with a compact, redacted prompt.
4. Merge only summarized results into the project prompt context.
5. Fall back to local memory/context cards when the service is unavailable.

## Behavioral Boundaries & Constraints
- **Optional only**: Never make OpenViking a hard runtime dependency for trading or execution.
- **No secrets**: Do not send raw logs, secrets, wallet data, Telegram private messages, or ledger data.
- **Compact context**: Pass concise search queries and summarize results before reinjection.
- **Local fallback**: Keep project memory and context cards as the source of truth if OpenViking is disabled or unreachable.

## Configuration
```bash
export OPENVIKING_ENABLED=true
export OPENVIKING_URL=http://127.0.0.1:1933
export OPENVIKING_API_KEY=...
export OPENVIKING_ACCOUNT=...
export OPENVIKING_USER=...
```

## Best Practices
1. Use OpenViking for compact retrieval of project notes and architecture context.
2. Keep all trading decisions behind parser, risk, ledger, and execution-mode checks.
3. Treat remote memory as advisory input, not as an execution authority.
