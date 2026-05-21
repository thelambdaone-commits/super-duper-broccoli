# Documentation Index

## Available Docs

- [`Ouroboros Integration`](./ouroboros_integration.md)
- [`Web-First Ingestion Architecture`](./web_first_architecture.md)
- [`API and MCP Surface`](./api_and_mcp.md)
- [`Execution and Risk`](./execution_and_risk.md)
- [`Telegram Ingestion`](./telegram_ingestion.md)
- [`Ledger and Wallets`](./ledger_and_wallets.md)
- [`Wallet Journal`](./wallet_journal.md)
- [`Configuration`](./configuration.md)
- [`Scripts and Training`](./scripts_and_training.md)
- [`Core Orchestration`](./core_orchestration.md)
- [`Continuous Improvement`](./continuous_improvement.md)
- [`Agentic Research Integrations`](./agentic_research_integrations.md)
- [`GSD Workflow Adaptation`](./gsd_workflow.md)
- [`Superpowers Workflow Adaptation`](./superpowers_workflow.md)
- [`Multi-Persona Prompts`](./multi_persona_prompts.md)
- [`Operational Dashboards`](./operational_dashboards.md)
- [`Utilities Reference`](./utilities_reference.md)

## Scope

These pages are intentionally narrow:

- `ouroboros_integration.md` documents the current compatibility wrapper, not the full Ouroboros product workflow.
- `web_first_architecture.md` documents the actual scraping, parsing, formatting, and persistence modules used today.
- `api_and_mcp.md` documents the HTTP and MCP surfaces that expose the core runtime.
- `execution_and_risk.md` documents sizing, execution modes, and ledger safeguards.
- `telegram_ingestion.md` documents the Telegram listener and command routing path.
- `ledger_and_wallets.md` documents ledger persistence, paper positions, and wallet state.
- `wallet_journal.md` documents the append-only Polymarket wallet snapshot file used for quick reconciliation.
- `configuration.md` documents the main constants and secret-loading policy.
- `scripts_and_training.md` documents the main maintenance and training entry points.
- `core_orchestration.md` documents the main orchestration and training pipeline modules.
- `continuous_improvement.md` documents the CI agent and project memory loop.
- `agentic_research_integrations.md` documents imported multi-agent, RL, and agentic-validation ideas.
- `gsd_workflow.md` documents the local spec-driven GSD adaptation and verification gates.
- `superpowers_workflow.md` documents the local spec-first, TDD-oriented Superpowers adaptation and verification gates.
- `multi_persona_prompts.md` documents trader/coder/ML/strategy/analyst/actuary prompts plus LLM Council, MiroFish, Ruflo, and Superpowers integration.
- `operational_dashboards.md` documents the Streamlit dashboard, paper execution, broadcast, and health probe utilities.
- `utilities_reference.md` documents the helper modules that support parsing, scanning, wallets, help text, and signal generation.

## Related Code

- [`utils/ouroboros_integration.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/ouroboros_integration.py)
- [`scrapers/web_scraper.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/scrapers/web_scraper.py)
- [`scrapers/clob_listener.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/scrapers/clob_listener.py)
- [`utils/output_formatter.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/output_formatter.py)
- [`utils/feature_store.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/feature_store.py)
- [`api/api_server.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/api/api_server.py)
- [`mcp_agents/mcp_server.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/mcp_agents/mcp_server.py)
- [`core/portfolio_risk_engine.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/core/portfolio_risk_engine.py)
- [`scrappers/mets_telegram_scraper.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/scrappers/mets_telegram_scraper.py)
- [`ledger/ledger_db.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/ledger/ledger_db.py)
- [`config/constants.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/config/constants.py)
- [`utils/vault_handler.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/vault_handler.py)
- [`scripts/train_all.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/scripts/train_all.py)
- [`scripts/rl_feedback_loop.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/scripts/rl_feedback_loop.py)
- [`core/orchestrator.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/core/orchestrator.py)
- [`core/training_pipeline.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/core/training_pipeline.py)
- [`models/predictive_engine.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/models/predictive_engine.py)
- [`monitors/polymarket_monitor.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/monitors/polymarket_monitor.py)
- [`continuous_improvement/agent.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/continuous_improvement/agent.py)
- [`api/dashboard.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/api/dashboard.py)
- [`execution/paper_engine.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/execution/paper_engine.py)
- [`scrapers/data_pipeline.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/scrapers/data_pipeline.py)
- [`scrapers/telegram_broadcaster.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/scrapers/telegram_broadcaster.py)
- [`core/health_monitor.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/core/health_monitor.py)
- [`core/services/gsd_workflow.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/core/services/gsd_workflow.py)
- [`core/services/superpowers_workflow.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/core/services/superpowers_workflow.py)
- [`utils/persona_prompts.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/persona_prompts.py)
- [`utils/signal_parser.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/signal_parser.py)
- [`utils/signal_generator.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/signal_generator.py)
- [`utils/market_scanner.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/market_scanner.py)
- [`utils/wallet_manager.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/wallet_manager.py)
- [`utils/polymarket_wallet_journal.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/polymarket_wallet_journal.py)
- [`utils/help_manager.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/help_manager.py)
