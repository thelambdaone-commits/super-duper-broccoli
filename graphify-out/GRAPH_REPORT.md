# Graph Report - .  (2026-05-16)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 1506 nodes · 2306 edges · 120 communities (81 shown, 39 thin omitted)
- Extraction: 78% EXTRACTED · 22% INFERRED · 0% AMBIGUOUS · INFERRED: 513 edges (avg confidence: 0.64)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `5d6c59d3`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 40|Community 40]]
- [[_COMMUNITY_Community 41|Community 41]]
- [[_COMMUNITY_Community 42|Community 42]]
- [[_COMMUNITY_Community 43|Community 43]]
- [[_COMMUNITY_Community 44|Community 44]]
- [[_COMMUNITY_Community 45|Community 45]]
- [[_COMMUNITY_Community 46|Community 46]]
- [[_COMMUNITY_Community 47|Community 47]]
- [[_COMMUNITY_Community 48|Community 48]]
- [[_COMMUNITY_Community 49|Community 49]]
- [[_COMMUNITY_Community 50|Community 50]]
- [[_COMMUNITY_Community 51|Community 51]]
- [[_COMMUNITY_Community 52|Community 52]]
- [[_COMMUNITY_Community 53|Community 53]]
- [[_COMMUNITY_Community 54|Community 54]]
- [[_COMMUNITY_Community 55|Community 55]]
- [[_COMMUNITY_Community 56|Community 56]]
- [[_COMMUNITY_Community 57|Community 57]]
- [[_COMMUNITY_Community 58|Community 58]]
- [[_COMMUNITY_Community 59|Community 59]]
- [[_COMMUNITY_Community 60|Community 60]]
- [[_COMMUNITY_Community 61|Community 61]]
- [[_COMMUNITY_Community 62|Community 62]]
- [[_COMMUNITY_Community 63|Community 63]]
- [[_COMMUNITY_Community 64|Community 64]]
- [[_COMMUNITY_Community 65|Community 65]]
- [[_COMMUNITY_Community 66|Community 66]]
- [[_COMMUNITY_Community 67|Community 67]]
- [[_COMMUNITY_Community 68|Community 68]]
- [[_COMMUNITY_Community 69|Community 69]]
- [[_COMMUNITY_Community 70|Community 70]]
- [[_COMMUNITY_Community 72|Community 72]]
- [[_COMMUNITY_Community 73|Community 73]]
- [[_COMMUNITY_Community 74|Community 74]]
- [[_COMMUNITY_Community 75|Community 75]]
- [[_COMMUNITY_Community 76|Community 76]]
- [[_COMMUNITY_Community 77|Community 77]]
- [[_COMMUNITY_Community 78|Community 78]]
- [[_COMMUNITY_Community 79|Community 79]]
- [[_COMMUNITY_Community 80|Community 80]]
- [[_COMMUNITY_Community 81|Community 81]]
- [[_COMMUNITY_Community 82|Community 82]]
- [[_COMMUNITY_Community 83|Community 83]]
- [[_COMMUNITY_Community 84|Community 84]]
- [[_COMMUNITY_Community 85|Community 85]]
- [[_COMMUNITY_Community 86|Community 86]]
- [[_COMMUNITY_Community 87|Community 87]]
- [[_COMMUNITY_Community 88|Community 88]]
- [[_COMMUNITY_Community 89|Community 89]]
- [[_COMMUNITY_Community 90|Community 90]]
- [[_COMMUNITY_Community 101|Community 101]]
- [[_COMMUNITY_Community 102|Community 102]]
- [[_COMMUNITY_Community 103|Community 103]]
- [[_COMMUNITY_Community 104|Community 104]]
- [[_COMMUNITY_Community 117|Community 117]]
- [[_COMMUNITY_Community 118|Community 118]]

## God Nodes (most connected - your core abstractions)
1. `PortfolioRiskEngine` - 45 edges
2. `FeatureStore` - 43 edges
3. `PassiveExecutor` - 40 edges
4. `Ledger` - 39 edges
5. `HybridQuantModel` - 38 edges
6. `TelegramListener` - 37 edges
7. `HMMRegimeFilter` - 33 edges
8. `ProbabilityCalibrator` - 33 edges
9. `ArbitrageScanner` - 30 edges
10. `TrainingPipeline` - 30 edges

## Surprising Connections (you probably didn't know these)
- `resolve_chat()` --calls--> `VaultHandler`  [INFERRED]
  main_agentic_clob.py → utils/vault_handler.py
- `store()` --calls--> `FeatureStore`  [INFERRED]
  tests/test_feature_store.py → utils/feature_store.py
- `executor()` --calls--> `PassiveExecutor`  [INFERRED]
  tests/test_passive_executor.py → execution/passive_executor.py
- `TestMakerFirst` --uses--> `PassiveExecutor`  [INFERRED]
  tests/test_passive_executor.py → execution/passive_executor.py
- `TestTakerOnly` --uses--> `PassiveExecutor`  [INFERRED]
  tests/test_passive_executor.py → execution/passive_executor.py

## Communities (120 total, 39 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.05
Nodes (17): HybridQuantModel, TFTEmbeddingHook, train_model_from_store(), GatedLinearUnit, GatedResidualNetwork, MultiHeadAttention, TemporalFusionTransformer, model() (+9 more)

### Community 1 - "Community 1"
Cohesion: 0.05
Nodes (18): TrainingPipeline, _batch_features(), compute_top1pct(), generate_synthetic_data(), main(), Progress, save_tracking(), train_configs() (+10 more)

### Community 2 - "Community 2"
Cohesion: 0.05
Nodes (53): API Server (FastAPI), Architecture, code:block1 (Telegram Channel / Private Chat), code:bash (curl "http://127.0.0.1:8000/v1/market-intelligence/crypto?li), code:bash (python scripts/discover_free_ai_providers.py), code:bash (python scripts/llm_council.py "Should this trading change sh), code:bash (python scripts/mirofish_plan.py "What could move SOL-related), code:bash (# Dry-run validation (no external connections)) (+45 more)

### Community 3 - "Community 3"
Cohesion: 0.05
Nodes (8): ArbitrageScanner, scanner(), TestConditionalOverpricing, TestMispricingIPV, TestOpportunityManagement, TestSumInefficiency, TestThreshold, TestToSignals

### Community 4 - "Community 4"
Cohesion: 0.07
Nodes (19): _market_scan_loop(), _fmt_signal(), format_market_report(), format_scan_report(), format_winning_bets_alert(), MarketScanner, MarketSignal, ScanResult (+11 more)

### Community 5 - "Community 5"
Cohesion: 0.05
Nodes (16): emergency_circuit_breaker(), get_arbitrage_opportunities(), v1_arbitrage(), v1_circuit_breaker(), archive_maintenance(), CommandRouter, archiver(), TestArchiveCleanup (+8 more)

### Community 6 - "Community 6"
Cohesion: 0.07
Nodes (17): Autonomous Quant Infrastructure Supervisor.     Analyzes system state, detects i, Records an incident for future learning., Analyzes logs to detect patterns of failure or inefficiency., Uses LLM to generate a code improvement patch., Generates a structured report for the Telegram supervisor., Placeholder for autonomous PR generation., SelfImprovementAgent, _safe_signal_for_log() (+9 more)

### Community 7 - "Community 7"
Cohesion: 0.07
Nodes (19): LobstarAgent, PolymarketMonitor, _cleanup_tasks(), _confirm_and_cleanup(), _drain_pending_tasks(), _handle_onchain_signal(), _health_check_loop(), on_signal() (+11 more)

### Community 8 - "Community 8"
Cohesion: 0.06
Nodes (33): 1. **No External Dependencies**, 2. **Deterministic Dual-Path Testing**, 3. **Hardware Circuit Breaker Validation**, 4. **Passive Order Mocking**, 5. **Ledger Assertions**, code:bash (cd ~/quant-agentic-trading-core-v2), code:bash (python3 -m pytest tests/test_system_integrity.py --tb=short ), code:bash (python3 -m pytest tests/test_system_integrity.py --cov=. --c) (+25 more)

### Community 9 - "Community 9"
Cohesion: 0.06
Nodes (32): 1. **Core Test Suite**, 2. **Comprehensive Report**, 3. **Execution Script**, **Alternative Methods**, 🏗️ Architecture Layers Tested, 📝 Code Quality, code:block1 (📄 tests/test_system_integrity.py), code:block2 (📄 TEST_SYSTEM_INTEGRITY_REPORT.md) (+24 more)

### Community 10 - "Community 10"
Cohesion: 0.12
Nodes (5): CIRegistry, run_analysis(), run_command(), CodeAnalyzer, TestImprover

### Community 11 - "Community 11"
Cohesion: 0.1
Nodes (10): RuntimeError, ProbabilityCalibrator, TestCalibrate, TestCalibrationImprovement, TestFusionModes, TestPredictProba, _load_fetcher(), Fetch a page with Scrapling and return text values for a CSS selector. (+2 more)

### Community 12 - "Community 12"
Cohesion: 0.13
Nodes (12): BaseModel, FreqAIEngine, ActionRequest, lifespan(), _make_timeout_calibrator(), MispricingRequest, ModeRequest, SentimentBatchRequest (+4 more)

### Community 13 - "Community 13"
Cohesion: 0.14
Nodes (18): execute_lobstar_signal(), execute_regex_signal(), MockLedger, test_executor_passed_through_for_prod(), test_incomplete_decision_skipped(), test_invalid_price_skipped(), test_lobstar_confidence_edge_case(), test_low_confidence_skipped() (+10 more)

### Community 14 - "Community 14"
Cohesion: 0.07
Nodes (8): get_executor_metrics(), get_feature_store_stats(), get_ledger_state(), get_market_regime(), v1_executor_metrics(), v1_feature_store(), v1_ledger(), v1_regime()

### Community 15 - "Community 15"
Cohesion: 0.08
Nodes (25): 🔑 Authentication Details, code:block1 (======================== test session starts ===============), code:block2 (tests/test_system_integrity.py (608 lines, 23 KB)), code:block3 (feat: Complete system integrity test suite - 19/19 tests pas), code:block4 (origin    → git@github.com:thelambdaone-commits/super-duper-), code:bash (cat /home/ogj9f33gvvzc/quant-agentic-trading-core-v2/deploy_), code:bash (cd ~/quant-agentic-trading-core-v2), code:bash (cd ~/quant-agentic-trading-core-v2) (+17 more)

### Community 16 - "Community 16"
Cohesion: 0.08
Nodes (8): store(), TestDecisions, TestFeatures, TestFeatureStoreSchema, TestMicrostructure, TestPurge, TestReplayCursor, TestSignals

### Community 17 - "Community 17"
Cohesion: 0.16
Nodes (16): v1_crypto_market_intelligence(), main(), make_market(), test_analyze_filters_crypto_markets(), test_extreme_probability_is_crowded_flag(), test_report_format_and_json_are_stable(), test_short_crypto_tickers_do_not_match_word_fragments(), test_thin_liquidity_is_risk_flag() (+8 more)

### Community 18 - "Community 18"
Cohesion: 0.13
Nodes (14): build_feature_matrix(), compute_microstructure_features(), compute_order_imbalance(), compute_order_imbalance_from_frame(), compute_trade_imbalance(), polymarket_time_decay_weight(), polymarket_time_to_resolution(), ternary_agreement_model() (+6 more)

### Community 19 - "Community 19"
Cohesion: 0.18
Nodes (19): main(), test_build_project_prompt_context_includes_memory_and_graphify_policy(), _approx_tokens(), build_project_prompt_context(), _default_memory(), format_project_prompt_context(), list_project_memory(), _load_graphify_summary() (+11 more)

### Community 20 - "Community 20"
Cohesion: 0.1
Nodes (13): decrypt_data(), get_encryption_key(), Redacts common secret patterns from logs., Applies scrubbing filters to all root handlers., Gets or creates a local encryption key., Overwrites a file with random data before deleting it., SecretScrubbingFilter, secure_delete() (+5 more)

### Community 21 - "Community 21"
Cohesion: 0.22
Nodes (3): KnowledgeBase, _load(), _save()

### Community 22 - "Community 22"
Cohesion: 0.14
Nodes (6): init_components(), SentimentAnalyzer, analyzer(), TestBatchAnalysis, TestDeberta, TestFeatureVector

### Community 24 - "Community 24"
Cohesion: 0.11
Nodes (10): Exception, executor(), test_post_order_raises_exception(), test_queue_exception_during_await(), test_taker_failure(), test_taker_fallback_during_maker_error_in_await(), test_taker_without_maker(), TestEdgeCases (+2 more)

### Community 25 - "Community 25"
Cohesion: 0.1
Nodes (19): chairman_model, council_models, max_models_per_query, max_tokens, provider, api_key_env, api_key_vault_key, base_url (+11 more)

### Community 26 - "Community 26"
Cohesion: 0.12
Nodes (11): _execute_guarded(), test_paper_mode_records_virtual(), test_prod_mode_executes_full_size(), test_regex_signal_prod_executes(), test_regex_signal_uses_ledger_mode(), test_replay_mode_skips_execution(), test_shadow_mode_executes_mini_size(), test_zero_size_skipped() (+3 more)

### Community 27 - "Community 27"
Cohesion: 0.17
Nodes (14): HTMLParser, get_ai_specialist_prompt_context(), list_ai_specialists(), discover_candidates(), fetch_text(), GitHubRepoParser, main(), build_specialist_prompt_context() (+6 more)

### Community 28 - "Community 28"
Cohesion: 0.18
Nodes (9): GitDeployer, main(), Test SSH key connectivity, Push to specified remote, Execute full deployment pipeline, Execute shell command and return stdout, stderr, returncode, Run pytest to verify all tests pass, Verify the commit exists (+1 more)

### Community 29 - "Community 29"
Cohesion: 0.33
Nodes (17): check_python(), cleanup(), create_logs_dir(), ensure_vault_env(), generate_env(), install_deps(), install_vault(), log_error() (+9 more)

### Community 30 - "Community 30"
Cohesion: 0.16
Nodes (11): get_llm_council_config(), Protocol, test_redact_secret_like_text_handles_multiple_markers(), ChatClient, CouncilOpinion, CouncilResult, CouncilReview, load_llm_council_config() (+3 more)

### Community 31 - "Community 31"
Cohesion: 0.12
Nodes (14): hmm_filter(), ledger_in_memory(), mock_freqai(), probability_calibrator(), Unified End-to-End System Integrity Test Suite Verifies all 10 architectural lay, Mock FreqAIEngine for testing without live Polymarket CLOB., Layer 6: In-memory Ledger with SQLite WAL for atomic transactions., Layer 4: Probability Calibrator validates confidence scores. (+6 more)

### Community 33 - "Community 33"
Cohesion: 0.16
Nodes (7): test_get_all_configured_chains_fallback_labels(), test_get_all_configured_chains_labels(), test_resolve_rpc_with_fallback_uses_env_first(), test_resolve_rpc_with_fallback_uses_fallback_when_env_missing(), get_all_configured_chains(), get_rpc_url(), resolve_rpc_with_fallback()

### Community 35 - "Community 35"
Cohesion: 0.34
Nodes (13): apply_patch(), call_ai_cli(), collect_failures(), create_branch_and_commit(), dump_repo_snapshot(), extract_patch_from_ai(), find_ai_cli(), main() (+5 more)

### Community 36 - "Community 36"
Cohesion: 0.17
Nodes (11): mode, policy, goal, manual_validation_required, not_goal, respect_rate_limits, store_secrets, provider_classes (+3 more)

### Community 37 - "Community 37"
Cohesion: 0.17
Nodes (11): agent_cohorts, default_agents, default_rounds, guardrails, license_note, max_agents, max_rounds, purpose (+3 more)

### Community 38 - "Community 38"
Cohesion: 0.17
Nodes (8): Layer 5: Portfolio risk engine constraints., Initialize portfolio risk engine with exposure limits., Layer 7: Passive Executor with maker-first strategy + post_only flag., Layer 10: Complete end-to-end integration test., TestLayer10EndToEndIntegration, TestLayer5RiskManagement, TestLayer7PassiveExecutor, SignalParser

### Community 42 - "Community 42"
Cohesion: 0.18
Nodes (3): engine(), TestHighVolMultiplierConsistency, TestNetBetaExposure

### Community 43 - "Community 43"
Cohesion: 0.2
Nodes (9): routing_policy, default_context_budget_tokens, free_provider_mode, never_do, prefer_context_cards, prefer_local_models, token_saving_rules, specialists (+1 more)

### Community 44 - "Community 44"
Cohesion: 0.24
Nodes (3): QuantFatal, Non-recoverable system error — logged once, exit handled by entry point., Patch allowlisted optional provider keys into Vault without logging values.

### Community 45 - "Community 45"
Cohesion: 0.29
Nodes (6): apply_embargo(), combinatorial_purged_cv(), friction_adjusted_returns(), friction_sharpe_ratio(), purge_overlapping_labels(), purged_cv_score()

### Community 47 - "Community 47"
Cohesion: 0.29
Nodes (7): get_mirofish_config(), test_mirofish_config_loads_guardrails(), test_mirofish_plan_bounds_counts_and_redacts_seed_materials(), _bounded_int(), build_mirofish_simulation_plan(), build_mirofish_trading_research_brief(), load_mirofish_config()

### Community 48 - "Community 48"
Cohesion: 0.24
Nodes (7): MockVaultHandler, Layer 1: Vault credentials injection (no external Vault required)., Verify synthetic credentials are injected directly into RAM., Injects synthetic credentials directly into RAM without live Vault., Simulate Vault credential retrieval., test_full_system_pipeline_deterministic_dual_path(), TestLayer1VaultSynthetic

### Community 51 - "Community 51"
Cohesion: 0.25
Nodes (4): Discovers and imports all strategies in the directory., Aggregates signals from all running strategies., Orchestrates multiple independent trading strategies.     Supports dynamic loadi, StrategyManager

### Community 59 - "Community 59"
Cohesion: 0.32
Nodes (5): build_llm_council_plan(), run_llm_council_query(), main(), ask_llm_council_sync(), LLMCouncil

### Community 60 - "Community 60"
Cohesion: 0.25
Nodes (5): Layer 6: Ledger circuit breaker truncates rogue allocations., Simulate rogue agent allocating 50% of capital; circuit breaker caps at 5%., Verify SQLite atomic transactions with synchronous pragmas., Circuit breaker rejects order when capital insufficient., TestLayer6CircuitBreakerAndLedger

### Community 61 - "Community 61"
Cohesion: 0.25
Nodes (5): Layer 8: PAPER, SHADOW, PROD execution modes., PAPER mode records virtual positions without live capital., SHADOW mode uses 1% of nominal size., Invalid execution mode raises ValueError., TestLayer8ExecutionModes

### Community 62 - "Community 62"
Cohesion: 0.29
Nodes (6): server, description, name, transport, version, tools

### Community 63 - "Community 63"
Cohesion: 0.29
Nodes (6): 1. Textual Gradient Descent (TextGrad), 2. Evolutionary Prompting (EvoPrompt), 3. Graph Optimization (AFlow), Applicability to Quant Cockpit, Core Concepts, Reference: EvoAgentX Self-Evolving Architecture

### Community 67 - "Community 67"
Cohesion: 0.48
Nodes (4): _config(), FakeChatClient, test_llm_council_build_plan_redacts_secret_like_text(), test_llm_council_runs_opinion_review_and_chairman_stages()

### Community 69 - "Community 69"
Cohesion: 0.33
Nodes (5): agent_frameworks, agent_methodologies, context_compression, market_intelligence, web_scraping

### Community 70 - "Community 70"
Cohesion: 0.53
Nodes (5): list_project_contexts(), get_project_context(), list_local_skill_contexts(), list_project_contexts(), load_project_contexts()

### Community 73 - "Community 73"
Cohesion: 0.33
Nodes (4): Layer 9: Position tracking with SQLite persistence., Verify paper positions persist in SQLite., Verify position closure updates status in SQLite., TestLayer9PositionTracking

### Community 74 - "Community 74"
Cohesion: 0.33
Nodes (4): Layer 2: Signal ingestion via RegEx with sub-1ms interception., Path A: RegEx intercepts high-priority standardized Telegram signal., Verify RegEx handles multiple asset formats., TestLayer2SignalIngestion

### Community 75 - "Community 75"
Cohesion: 0.33
Nodes (4): Layer 3: HMM Regime Filter evaluates market state., HMM classifies returns into LOW_VOLATILITY, HIGH_TREND_VOLATILITY, or ERRATIC., HMM blocks execution during ERRATIC_VOLATILITY regime., TestLayer3HMMRegimeFilter

### Community 79 - "Community 79"
Cohesion: 0.4
Nodes (4): local_skills, projects, purpose, version

### Community 80 - "Community 80"
Cohesion: 0.4
Nodes (4): entries, purpose, updated_at, version

### Community 86 - "Community 86"
Cohesion: 0.83
Nodes (3): dump_project(), iter_project_files(), main()

## Knowledge Gaps
- **162 isolated node(s):** `version`, `purpose`, `updated_at`, `entries`, `TestExecuteRegexSignal` (+157 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **39 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `TelegramTokenRedactionFilter` connect `Community 7` to `Community 1`, `Community 34`, `Community 4`, `Community 5`, `Community 6`, `Community 39`, `Community 40`, `Community 41`, `Community 12`, `Community 44`, `Community 23`?**
  _High betweenness centrality (0.096) - this node is a cross-community bridge._
- **Why does `FeatureStore` connect `Community 23` to `Community 1`, `Community 5`, `Community 7`, `Community 12`, `Community 44`, `Community 16`, `Community 22`?**
  _High betweenness centrality (0.094) - this node is a cross-community bridge._
- **Why does `TrainingPipeline` connect `Community 1` to `Community 0`, `Community 12`, `Community 23`, `Community 7`?**
  _High betweenness centrality (0.092) - this node is a cross-community bridge._
- **Are the 35 inferred relationships involving `PortfolioRiskEngine` (e.g. with `init_components()` and `ModeRequest`) actually correct?**
  _`PortfolioRiskEngine` has 35 INFERRED edges - model-reasoned connections that need verification._
- **Are the 24 inferred relationships involving `FeatureStore` (e.g. with `init_components()` and `ModeRequest`) actually correct?**
  _`FeatureStore` has 24 INFERRED edges - model-reasoned connections that need verification._
- **Are the 30 inferred relationships involving `PassiveExecutor` (e.g. with `ModeRequest` and `ActionRequest`) actually correct?**
  _`PassiveExecutor` has 30 INFERRED edges - model-reasoned connections that need verification._
- **Are the 25 inferred relationships involving `Ledger` (e.g. with `ModeRequest` and `ActionRequest`) actually correct?**
  _`Ledger` has 25 INFERRED edges - model-reasoned connections that need verification._