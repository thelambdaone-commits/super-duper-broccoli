# External Project Absorption Audit

Date: 2026-05-23

## Scope

Projects reviewed:

- `pinglucid/polymarket-bot`
- `pinglucid/pmxt_v2_adapter`

## Absorption Status

### `pmxt_v2_adapter`

Status: absorbed as an offline utility under `scripts/pmxt_adapter/`.

What was integrated:

- `v2_to_v1_adapter.py`
- `extend_side_map_gamma.py`
- conversion and side-map documentation

Why this is complete enough:

- The adapter is self-contained and does not overlap with the runtime trading loop.
- Its purpose is archival conversion and replay preparation, not live execution.
- The repo previously lacked a PMXT v2 -> legacy v1 conversion path.

Remaining gaps:

- `polars` was not previously part of the local runtime stack; it is now declared as a dependency.
- No production code currently calls these tools automatically. They are intentionally operator-invoked.

### `polymarket-bot`

Status: not absorbed wholesale; selectively reviewed and mapped against existing components.

Reason:

- It is a full second bot with its own runtime, orchestration, risk, executor, market monitor, and strategy layer.
- Merging it as-is would duplicate critical responsibilities already implemented in this repo.

Covered already by this repo:

- orchestration and async signal queue: `core/orchestrator.py`
- live CLOB ingestion: `scrapers/clob_listener.py`
- execution and maker/taker handling: `execution/passive_executor.py`
- sizing and portfolio risk: `core/portfolio_risk_engine.py`
- Telegram operations and control plane: `telegram_scraper/`
- feature storage and archival: `utils/feature_store.py`, `utils/data_archiver.py`

Useful ideas identified but not yet imported:

- robust market metadata loader with Gamma pagination and local orderbook cache
- backtest and walk-forward tooling organization
- category-oriented AI knowledge base layout

## Missing Pieces After This Pass

The only clearly missing functionality from the two reviewed projects was PMXT archive compatibility, which is now present under `scripts/pmxt_adapter/`.

What is still intentionally not present:

- `polymarket-bot` TUI dashboard
- `polymarket-bot` standalone runtime and config model
- `polymarket-bot` executor/risk stack

These are omissions by design, not incomplete absorption.

