# Ledger Migrations

Ledger schema changes should be recorded here before being applied in code.

Current behavior remains in `ledger/ledger_db.py`, which performs idempotent
schema initialization and column upgrades. The next safe step is to add a
`schema_migrations` table and replay numbered SQL migrations from this folder.

Do not replace the current ledger initialization with an ORM migration in a
single change. The ledger is a capital-control component and needs incremental,
tested schema evolution.

