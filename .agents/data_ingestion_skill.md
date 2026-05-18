# 🌐 Data Ingestion Skill

*Moltbook-inspired Agentic Skill Document for market data normalization, freshness checks, and source quality control.*

## 1. Purpose
Ensures market data entering the system is normalized, timestamped, deduplicated, and fresh enough for downstream signal generation.

## 2. Trigger Conditions
* New scrape or CLOB snapshot arrives.
* A pipeline job detects stale or missing data.
* A model or signal requires source validation before use.

## 3. Execution Steps
1. Normalize timestamps and symbol casing.
2. Check freshness, gaps, missing fields, and duplicate snapshots.
3. Validate source quality before publishing to downstream consumers.
4. Emit compact diagnostics for monitoring and test coverage.

## 4. Behavioral Boundaries & Constraints
* Do not fabricate missing market values.
* Do not send raw secrets or private data to external systems.
* Preserve the original raw payload for audit only when policy allows.
