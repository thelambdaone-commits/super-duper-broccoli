from __future__ import annotations

import asyncio
import os
from typing import Any

from bootstrap.helpers import run_blocking
from utils.config_loader import get_trading_config
import logging

logger = logging.getLogger("Scheduler")


def _setup_ml_features(training_pipeline: Any, tickers: list[str] | None = None) -> None:
    tickers = tickers or get_trading_config("model_tickers", ["SOL", "BTC", "ETH"], allow_env=False)
    default_features = ["oi_5min", "tam_state", "spread_bps", "mid_price"]
    for ticker in tickers:
        training_pipeline.register_features(ticker, default_features, target_feature="mid_price")


def _setup_autonomous_trading(
    runner: Any,
    ledger: Any,
    store: Any,
    risk: Any,
    scanner: Any,
    cognitive_brain: Any,
    executor: Any = None,
) -> None:
    try:
        from core.autonomous_trading_loop import AutonomousTradingLoop
        from user_data.strategies.polymarket_strategy_factory import build_default_polymarket_strategies
        from core.strategy_lifecycle_manager import StrategyLifecycleManager

        lifecycle = StrategyLifecycleManager()
        strategies = build_default_polymarket_strategies()
        for s in strategies:
            lifecycle.register_strategy(s)

        loop = AutonomousTradingLoop(
            ledger=ledger,
            lifecycle=lifecycle,
            risk_engine=risk,
            feature_store=store,
            price_provider=scanner,
            executor=executor,
        )

        async def run_autonomous_cycle():
            features = []
            if scanner and hasattr(scanner, "get_strategy_features"):
                try:
                    features = scanner.get_strategy_features() or []
                except Exception as exc:
                    logger.warning("Autonomous strategy feature extraction failed: %s", exc)
            await loop.run_once(features)

        runner.register_job("Autonomous_Trading_Loop", run_autonomous_cycle, interval_sec=15.0)
        logger.info("✅ [SCHEDULER] Autonomous Trading Loop registered (15s interval)")
    except Exception as e:
        import logging
        logging.getLogger("Scheduler").warning(f"Failed to setup autonomous trading: {e}")


def _setup_quantum_runner(
    runner: Any,
    freqai: Any,
    cognitive_brain: Any,
    mlops_engine: Any,
    autonomic_healer: Any,
    broadcaster: Any,
    *,
    runtime_secrets: dict[str, str] | None = None,
    feature_store: Any = None,
    ledger: Any = None,
    training_pipeline: Any = None,
    risk: Any = None,
    scanner: Any = None,
    executor: Any = None,
    orchestrator: Any = None,
) -> None:
    runtime_secrets = runtime_secrets or {}

    # Setup Swarm Supervisor (Aulekator Integration)
    try:
        from core.swarm_supervisor import initialize_swarm_supervisor
        mode = ledger.get_execution_mode() if ledger else "PAPER"
        
        # We store a reference to prevent GC and allow for future status checks
        def _on_swarm_init_done(task: asyncio.Task) -> None:
            try:
                task.result()
                logger.info("🐝 [SCHEDULER] Swarm Supervisor initialization completed successfully.")
            except Exception as exc:
                logger.error(f"❌ [SCHEDULER] Swarm Supervisor initialization failed: {exc}")

        init_task = asyncio.create_task(initialize_swarm_supervisor(mode=mode))
        init_task.add_done_callback(_on_swarm_init_done)
        
        # Keep a strong reference for visibility and to avoid premature cleanup.
        runner._swarm_init_task = init_task

        logger.info(f"🐝 [SCHEDULER] Swarm Supervisor initialization task started (Mode: {mode})")
    except Exception as e:
        logger.warning(f"Failed to trigger Swarm Supervisor initialization: {e}")

    # Setup Autonomous Trading Loop
    _setup_autonomous_trading(
        runner=runner,
        ledger=ledger,
        store=feature_store,
        risk=risk,
        scanner=scanner,
        cognitive_brain=cognitive_brain,
        executor=executor,
    )

    runner.register_job("Web_Scraper_Ticks", freqai.stream_ticks_to_duckdb, interval_sec=0.1)
    if getattr(cognitive_brain, "arbitrage_engine", None):
        runner.register_job("Arbitrage_Matrix_Scan", cognitive_brain.arbitrage_engine.scanner_anomalies, interval_sec=5.0)
    runner.register_job("MLOps_Health_Check", mlops_engine.analyser_sante_brain, interval_sec=14400.0)

    async def adaptive_weight_optimization():
        if not orchestrator or not ledger:
            return
        try:
            # Phase 7 Aulekator: Adaptive Learning
            # We prefer REAL performance if available, fallback to aggregate
            perf_summary = ledger.get_performance_summary_by_source(mode="PROD")
            if not perf_summary:
                perf_summary = ledger.get_performance_summary_by_source()

            if hasattr(orchestrator, "fusion_engine"):
                orchestrator.fusion_engine.update_weights_from_pnl(perf_summary)
        except Exception as e:
            logger.warning(f"Adaptive weight optimization failed: {e}")

    runner.register_job("Adaptive_Weight_Optimization", adaptive_weight_optimization, interval_sec=3600.0)

    async def prune_feature_store():
        store = feature_store or getattr(cognitive_brain, "store", None)
        if store and mlops_engine.should_prune(interval_hours=24):
            mlops_engine.prune_feature_store(store, raw_retention_days=7, vacuum=True)

    os.makedirs(os.path.dirname(autonomic_healer.log_path), exist_ok=True)

    async def run_healer():
        errors = autonomic_healer.analyser_nouveaux_logs()
        for err in errors:
            await autonomic_healer.deployer_correctif_autonome(err)

    runner.register_job("Autonomic_Healer", run_healer, interval_sec=2.0)
    runner.register_job("FeatureStore_Prune", prune_feature_store, interval_sec=3600.0)

    async def system_connectivity_check():
        import httpx
        from utils.api_key_check import get_api_key_notifier

        api_check = get_api_key_notifier().check_all_keys(runtime_secrets=runtime_secrets)
        if api_check["missing"]:
            alert = get_api_key_notifier().format_telegram_alert(api_check)
            if broadcaster and broadcaster.notifier:
                await broadcaster.notifier.send_async(alert, parse_mode="HTML")

        timeout = httpx.Timeout(5.0, connect=3.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            rpc_url = runtime_secrets.get("POLYGON_RPC_URL")
            if rpc_url:
                try:
                    await asyncio.to_thread(lambda: None)
                except Exception:
                    pass
            try:
                await client.get("https://gamma-api.polymarket.com/tags?limit=1", timeout=3.0)
            except Exception:
                pass

    runner.register_job("System_Connectivity_Check", system_connectivity_check, interval_sec=1800.0)

    async def db_storage_optimization():
        if not ledger:
            return
        try:
            cursor = ledger.conn.cursor()
            cursor.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            cursor.execute("PRAGMA optimize")
        except Exception as exc:
            import logging

            logging.getLogger(__name__).warning("DB storage optimization failed: %s", exc)

    runner.register_job("DB_Storage_Optimization", db_storage_optimization, interval_sec=7200.0)

    async def dynamic_ml_reinforcement():
        if not training_pipeline or not ledger:
            return
        from scripts.rl_feedback_loop import run_rl_feedback_loop

        await run_blocking("RL feedback loop", run_rl_feedback_loop, timeout=120.0)
        tickers = get_trading_config("model_tickers", ["SOL", "BTC", "ETH"], allow_env=False)
        if isinstance(tickers, str):
            tickers = tickers.split(",")
        for ticker in [str(t).strip().upper() for t in tickers if str(t).strip()]:
            training_pipeline.update_calibration_from_paper_trades(ticker, ledger)

    runner.register_job("Dynamic_ML_Reinforcement", dynamic_ml_reinforcement, interval_sec=1800.0)

    async def daily_tca_report_job():
        from scripts.daily_tca_report import DailyTcaReportConfig, DailyTcaReportJob

        metrics_log_path = os.getenv("EXECUTION_METRICS_LOG_PATH", "user_data/data/execution_metrics.jsonl")
        state_path = os.path.join(os.path.dirname(metrics_log_path), "daily_tca_state.json")
        config = DailyTcaReportConfig(metrics_log_path=metrics_log_path, state_path=state_path)
        job = DailyTcaReportJob(broadcaster, config)
        await job.run()

    runner.register_job("Daily_TCA_Report", daily_tca_report_job, interval_sec=86400.0)

    async def train_and_rotate_models():
        if training_pipeline:
            tickers = get_trading_config("model_tickers", ["SOL", "BTC", "ETH"], allow_env=False)
            if isinstance(tickers, str):
                tickers = tickers.split(",")
            for ticker in [str(t).strip().upper() for t in tickers if str(t).strip()]:
                await run_blocking(f"training rotation {ticker}", training_pipeline.run_cycle, ticker, timeout=300.0)

    runner.register_job("Train_And_Rotate_Models", train_and_rotate_models, interval_sec=21600.0)
