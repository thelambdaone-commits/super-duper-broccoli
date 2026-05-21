from __future__ import annotations

import asyncio
import os
from typing import Any

from bootstrap.helpers import run_blocking


def _setup_ml_features(training_pipeline: Any, tickers: list[str] | None = None) -> None:
    tickers = tickers or ["SOL", "BTC", "ETH"]
    default_features = ["oi_5min", "tam_state", "spread_bps", "mid_price"]
    for ticker in tickers:
        training_pipeline.register_features(ticker, default_features, target_feature="mid_price")


def _setup_quantum_runner(
    runner: Any,
    container: Any,
    freqai: Any,
    cognitive_brain: Any,
    mlops_engine: Any,
    autonomic_healer: Any,
    broadcaster: Any,
) -> None:
    runner.register_job("Web_Scraper_Ticks", freqai.stream_ticks_to_duckdb, interval_sec=0.1)
    if getattr(cognitive_brain, "arbitrage_engine", None):
        runner.register_job("Arbitrage_Matrix_Scan", cognitive_brain.arbitrage_engine.scanner_anomalies, interval_sec=5.0)
    runner.register_job("MLOps_Health_Check", mlops_engine.analyser_sante_brain, interval_sec=14400.0)

    async def prune_feature_store():
        store = getattr(cognitive_brain, "store", None) or getattr(container, "store", None)
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

        api_check = get_api_key_notifier().check_all_keys(runtime_secrets=container.secrets)
        if api_check["missing"]:
            alert = get_api_key_notifier().format_telegram_alert(api_check)
            if broadcaster and broadcaster.notifier:
                await broadcaster.notifier.send_async(alert, parse_mode="Markdown")

        timeout = httpx.Timeout(5.0, connect=3.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            rpc_url = container.secrets.get("POLYGON_RPC_URL") or os.getenv("POLYGON_RPC_URL")
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
        ledger = getattr(container, "ledger", None)
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
        pipeline = getattr(container, "training_pipeline", None)
        ledger = getattr(container, "ledger", None)
        if not pipeline or not ledger:
            return
        from scripts.rl_feedback_loop import run_rl_feedback_loop

        await run_blocking("RL feedback loop", run_rl_feedback_loop, timeout=120.0)
        tickers = os.getenv("MODEL_TICKERS", "SOL,BTC,ETH").split(",")
        for ticker in [t.strip().upper() for t in tickers if t.strip()]:
            pipeline.update_calibration_from_paper_trades(ticker, ledger)

    runner.register_job("Dynamic_ML_Reinforcement", dynamic_ml_reinforcement, interval_sec=1800.0)

    async def daily_tca_report_job():
        from scripts.daily_tca_report import DailyTcaReportConfig, DailyTcaReportJob

        job = DailyTcaReportJob(DailyTcaReportConfig())
        await job.run()

    runner.register_job("Daily_TCA_Report", daily_tca_report_job, interval_sec=86400.0)

    async def train_and_rotate_models():
        pipeline = getattr(container, "training_pipeline", None)
        if pipeline:
            await run_blocking("training rotation", pipeline.run_cycle, timeout=300.0)

    runner.register_job("Train_And_Rotate_Models", train_and_rotate_models, interval_sec=21600.0)
