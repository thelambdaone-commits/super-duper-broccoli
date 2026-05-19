# ADR 001: Progressive Structure Hardening

## Status
Accepted

## Context
The project runs live trading-adjacent services, Telegram ingestion, MCP tools,
and API/dashboard processes from the same repository. A large one-shot migration
to a new layout would create unnecessary import and deployment risk.

## Decision
Structural changes must be additive and compatibility-preserving first:

- New typed configuration starts in `config/settings.py`.
- New pure domain objects start in `domain/`.
- Existing modules keep their current import paths until their call sites are
  migrated and covered by tests.
- Runtime entrypoints remain stable while implementation is extracted behind
  them.
- Ledger schema evolution should be versioned before introducing any ORM.

## Consequences
This keeps the current PM2, CLI, API, and test workflows operational while
creating clear destinations for future refactors. Compatibility shims may exist
temporarily, but new code should prefer typed settings and domain types.

