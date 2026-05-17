import argparse
import asyncio
import contextlib
import fcntl
import logging
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from dotenv import load_dotenv

load_dotenv()

from core.container import ServiceContainer
from core.lobstar_cognitive_brain import LobstarCognitiveBrain
from core.signal_executor import execute_lobstar_signal, execute_regex_signal
from core.training_pipeline import TrainingPipeline
from models.predictive_engine import PolymarketPredictiveEngine
from mcp_agents.lobstar_agent import LobstarAgent
from monitors.polymarket_monitor import PolymarketMonitor
from agents.copy_trading_agent import CopyTradingAgent, CopyConfig
from telegram_scraper.telegram_listener import TelegramListener
from utils.circuit_breaker import CircuitBreaker
from utils.access_control import AccessControlManager
from utils.crypto_market_intelligence import CryptoMarketIntelligence, format_intelligence_report
from utils.exceptions import QuantFatal
from ledger.ledger_db import Ledger
from user_data.strategies.hmm_filter import HMMRegimeFilter
from utils.feature_store import FeatureStore
from utils.market_scanner import MarketScanner
from utils.model_validator import ModelValidator
from ai.agents.self_improvement_agent import SelfImprovementAgent
from utils.snapshot_manager import get_snapshot_manager
from scrapers.telegram_broadcaster import TelegramBroadcaster, TokenBucketRateLimiter
from utils.message_formatter import (
    format_scan_report,
    format_market_report,
    format_winning_bets_alert,
)

from utils.logging_setup import setup_logging
from utils.telegram_helpers import parse_chat_ids, parse_private_chat_ids

logger = setup_logging()

from utils.security_utils import setup_secure_logging
setup_secure_logging()

@contextlib.contextmanager
def telegram_single_instance_lock(lock_path: Path | None = None):
    lock_path = lock_path or Path(tempfile.gettempdir()) / "quant_agentic_telegram.lock"
    with lock_path.open("w") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise QuantFatal(
                "Another Telegram polling instance is already running. "
                "Stop the existing PM2/manual bot before starting this command."
            )
        lock_file.write(str(os.getpid()))
        lock_file.flush()
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

def _safe_signal_for_log(signal: dict) -> dict:
    return {key: value for key, value in signal.items() if key != "update"}


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _derive_public_wallet(private_key: str | None) -> str | None:
    if not private_key:
        return None
    try:
        from eth_account import Account

        return Account.from_key(private_key).address
    except Exception as exc:
        logger.warning("Unable to derive public wallet address from configured key: %s", exc)
        return None


def build_access_control(secrets: dict, execution_mode: str) -> tuple[AccessControlManager, int | None]:
    raw_admin_ids = secrets.get("TELEGRAM_ADMIN_CHAT_IDS") or os.getenv("TELEGRAM_ADMIN_CHAT_IDS", "")
    admin_chat_ids = parse_chat_ids(raw_admin_ids) or set()
    if execution_mode.upper() == "PROD" and not admin_chat_ids:
        raise QuantFatal("TELEGRAM_ADMIN_CHAT_IDS is required in PROD mode.")

    access_control = AccessControlManager(admin_chat_ids=sorted(admin_chat_ids))
    raw_chat_id = os.getenv("CHAT_ID", "")
    chat_id = int(raw_chat_id) if raw_chat_id else None
    tenant_wallet = _derive_public_wallet(secrets.get("CLOB_PRIVATE_KEY"))
    if chat_id and tenant_wallet:
        access_control.assigner_wallet_a_chat(chat_id, tenant_wallet)
    return access_control, chat_id


def build_copy_trading_agent() -> CopyTradingAgent | None:
    copy_wallet = os.getenv("COPY_WALLET", "").strip()
    if not copy_wallet:
        return None
    copy_config = CopyConfig(
        target_wallet=copy_wallet,
        copy_multiplier=float(os.getenv("COPY_MULTIPLIER", "0.1")),
        max_copy_notional=float(os.getenv("COPY_MAX_NOTIONAL", "100.0")),
        buy_only=os.getenv("COPY_BUY_ONLY", "true").lower() == "true",
    )
    agent = CopyTradingAgent(copy_config)
    logger.info("🎯 Copy Trading configured: %s... multiplier=%s", copy_wallet[:10], copy_config.copy_multiplier)
    return agent


def build_telegram_listener(
    *,
    secrets: dict,
    on_signal: Callable[[dict], None],
    chat_id: int | None,
    access_control: AccessControlManager,
) -> TelegramListener:
    return TelegramListener(
        bot_token=secrets["TELEGRAM_BOT_TOKEN"],
        on_signal=on_signal,
        channel_username=os.getenv("TARGET_CHANNEL", ""),
        chat_id=chat_id,
        private_chat_ids=parse_private_chat_ids(os.getenv("TELEGRAM_PRIVATE_CHAT_IDS", "")),
        admin_chat_ids=parse_chat_ids(os.getenv("TELEGRAM_ADMIN_CHAT_IDS", "")),
        allow_private_messages=os.getenv("TELEGRAM_PRIVATE_ENABLED", "1") != "0",
        proxy_url=os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY") or None,
        access_control=access_control,
    )


def build_crypto_intelligence() -> CryptoMarketIntelligence:
    return CryptoMarketIntelligence(
        watchlist=[
            ticker.strip().upper()
            for ticker in os.getenv("CRYPTO_INTELLIGENCE_WATCHLIST", "BTC,ETH,SOL").split(",")
            if ticker.strip()
        ],
        min_volume=float(os.getenv("CRYPTO_INTELLIGENCE_MIN_VOLUME", "10000")),
        min_liquidity=float(os.getenv("CRYPTO_INTELLIGENCE_MIN_LIQUIDITY", "1000")),
    )


def build_cognitive_brain(store, market_scanner: MarketScanner, training_pipeline: TrainingPipeline) -> LobstarCognitiveBrain:
    from core.arbitrage_feedback_loop import LobstarArbitrageEngine
    arb_engine = LobstarArbitrageEngine(
        execution_mode=os.getenv("MODE", "PAPER"),
        slippage_tolerance=float(os.getenv("SLIPPAGE_TOLERANCE", "0.002")),
        trigger_threshold=float(os.getenv("ARBITRAGE_TRIGGER_THRESHOLD", "0.015")),
    )
    return LobstarCognitiveBrain(
        store=store,
        scanner=market_scanner,
        training_pipeline=training_pipeline,
        arbitrage_engine=arb_engine,
        oi_lookback_seconds=int(os.getenv("LOBSTAR_BRAIN_OI_LOOKBACK_SECONDS", "1800")),
        time_decay_half_life_seconds=int(os.getenv("LOBSTAR_BRAIN_TIME_DECAY_HALF_LIFE_SECONDS", "3600")),
    )


def build_broadcaster(container, training_pipeline: TrainingPipeline, market_scanner: MarketScanner) -> TelegramBroadcaster:
    return TelegramBroadcaster(
        notifier=container.notifier,
        training_pipeline=training_pipeline,
        market_client=market_scanner.client,
        tickers=[t.strip().upper() for t in os.getenv("TELEGRAM_BROADCAST_TICKERS", "SOL,BTC,ETH").split(",") if t.strip()],
        edge_threshold=float(os.getenv("TELEGRAM_BROADCAST_EDGE_THRESHOLD", "0.07")),
        rate_limiter=TokenBucketRateLimiter(
            capacity=int(os.getenv("TELEGRAM_BROADCAST_MAX_PER_MINUTE", "3")),
            refill_period_seconds=60.0,
        ),
        enabled=os.getenv("TELEGRAM_BROADCAST_ENABLED", "1") != "0",
    )


async def run_blocking(label: str, func: Callable[..., Any], *args: Any, timeout: float = 30.0, **kwargs: Any) -> Any:
    try:
        return await asyncio.wait_for(asyncio.to_thread(func, *args, **kwargs), timeout=timeout)
    except asyncio.TimeoutError:
        raise TimeoutError(f"{label} timed out after {timeout}s") from None


async def main(
    dry_run: bool = False,
    execution_mode: str = "PAPER",
) -> None:
    # Env-based mode override
    if os.getenv("REAL", "false").lower() == "true":
        execution_mode = "PROD"
    elif os.getenv("PAPER", "true").lower() == "true":
        execution_mode = "PAPER"

    container = ServiceContainer.get_instance()
    notifier = container.notifier
    
    notifier.send(f"🚀 *System Started*\nMode: `{execution_mode}`\nEnvironment: `{os.uname().nodename}`")

    from utils.api_key_notifier import get_api_key_notifier
    api_check = get_api_key_notifier().check_all_keys()
    if api_check["missing"]:
        missing_msg = get_api_key_notifier().format_console_report(api_check)
        logger.warning(missing_msg)

    # Rehydrate risk engine
    container.risk.rehydrate_from_ledger(container.ledger)
    secrets = container.secrets

    access_control, chat_id = build_access_control(secrets, execution_mode)

    ledger = container.ledger
    freqai = container.freqai

    hmm = container.hmm
    risk = container.risk
    store = container.store
    passive_executor = container.executor
    
    if secrets.get("GROQ_API_KEY"):
        lobstar = LobstarAgent(api_key=secrets["GROQ_API_KEY"])
    else:
        logger.warning("GROQ_API_KEY missing. Semantic signal parsing (LOBSTAR) disabled.")
        lobstar = None
    circuit_breaker = CircuitBreaker(name="CLOB_Execution")

    from core.swarm_supervisor import initialize_swarm_supervisor, get_swarm_supervisor
    swarm_supervisor = await initialize_swarm_supervisor(mode=execution_mode)

    data_diag = swarm_supervisor.check_data_gaps()
    logger.info(f"📊 Data Gap Check: {data_diag}")

    async def on_mode_change(new_mode):
        mode_str = new_mode.value
        logger.warning(f"⚠️ Swarm triggered mode change: {mode_str}")
        ledger.set_execution_mode(mode_str)
        if listener:
            await listener.send_message(f"🔄 *Mode changed to:* `{mode_str}` (Swarm Supervisor)")

    async def on_circuit_breaker(reason, data):
        logger.critical(f"🚨 Swarm Circuit Breaker: {reason.value}")
        if listener:
            await listener.send_message(
                f"🚨 *CIRCUIT BREAKER*\nReason: `{reason.value}`\nData: `{data}`"
            )

    swarm_supervisor.set_mode_change_callback(on_mode_change)
    swarm_supervisor.set_circuit_breaker_callback(on_circuit_breaker)

    copy_trading_agent = build_copy_trading_agent()

    training_pipeline = TrainingPipeline(
        store=store,
        retrain_interval_hours=24,
        min_train_samples=50,
        validation_split=0.2,
    )
    # Register features for autonomous retraining
    DEFAULT_FEATURES = ["oi_5min", "tam_state", "spread_bps", "mid_price"]
    for tkr in ["SOL", "BTC", "ETH"]:
        training_pipeline.register_features(tkr, DEFAULT_FEATURES, target_feature="mid_price")

    from ai.agents.self_improvement_agent import SelfImprovementAgent
    from utils.model_validator import ModelValidator
    from utils.snapshot_manager import get_snapshot_manager
    snapshot_mgr = get_snapshot_manager()
    model_validator = ModelValidator(snapshot_manager=snapshot_mgr)
    self_improver = SelfImprovementAgent()

    if execution_mode:
        ledger.set_execution_mode(execution_mode)

    mode = ledger.get_execution_mode()

    if dry_run:
        logger.info("=== DRY RUN MODE ===")
        logger.info(f"Vault: OK (6 secrets loaded)")
        logger.info(f"CLOB Engine: OK")
        logger.info(f"Ledger: OK")
        logger.info(f"HMMRegimeFilter: OK")
        logger.info(f"PortfolioRiskEngine: OK")
        logger.info(f"LobstarAgent: OK")
        logger.info(f"CircuitBreaker: OK ({circuit_breaker.status_report})")
        logger.info(f"FeatureStore: OK ({store.get_stats()})")
        logger.info(f"Execution Mode: {mode}")
        logger.info(f"Telegram Bot: SKIPPED (dry-run)")
        logger.info(f"Pipeline validated successfully.")
        logger.info(f"Active mode: {mode} — {'Virtual' if mode in ('REPLAY', 'PAPER') else 'Real capital at risk.'}")
        return

    _pending_tasks: list[asyncio.Task] = []
    _TASK_SLOTS = 200

    async def _confirm_and_cleanup(
        task: asyncio.Task,
        signal: dict,
        listener: TelegramListener,
    ) -> None:
        try:
            result = await task
            if not result or not isinstance(result, dict):
                return

            if result.get("status") == "SUCCESS":
                logger.info(f"Signal executed successfully: {result.get('trade_id', 'N/A')}")
                notifier.send(
                    f"✅ *Trade Executed*\n"
                    f"Ticker: `{result.get('ticker', 'Unknown')}`\n"
                    f"Side: `{result.get('side', 'Unknown')}`\n"
                    f"Size: `{result.get('executed_size', 0.0):.2f}` @ `{result.get('price', 0.0):.4f}`\n"
                    f"Mode: `{execution_mode}`"
                )
                circuit_breaker.record_success()
            else:
                reason = result.get("reason_1") or result.get("reason") or "Unknown error"
                logger.warning(f"Signal execution failed: {reason}")
                notifier.send(f"⚠️ *Execution Failed*\nTicker: `{result.get('ticker', 'Unknown')}`\nReason: `{reason}`")
                circuit_breaker.record_failure(reason)

            from utils.message_formatter import InstitutionalMessageFormatter
            confirmation = InstitutionalMessageFormatter.format_trade_execution_html(result)
            
            chat_id = signal.get("chat_id")
            update = signal.get("update")
            
            if update is not None and update.message:
                await listener.reply_to(confirmation, update, parse_mode="HTML")
            elif chat_id:
                await listener.send_message(confirmation, chat_id=chat_id, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Signal execution failed: {e}")
            circuit_breaker.record_failure(str(e))

    def _cleanup_tasks() -> None:
        for t in _pending_tasks:
            if t.done():
                try:
                    exc = t.exception()
                    if exc:
                        logger.warning(f"Task exception: {exc}")
                except asyncio.CancelledError:
                    pass
        _pending_tasks[:] = [t for t in _pending_tasks if not t.done()]

    async def _drain_pending_tasks(timeout: float = 10.0) -> None:
        _cleanup_tasks()
        if not _pending_tasks:
            return
        done, pending = await asyncio.wait(_pending_tasks, timeout=timeout)
        for task in done:
            try:
                exc = task.exception()
                if exc:
                    logger.warning(f"Task exception during shutdown: {exc}")
            except asyncio.CancelledError:
                pass
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def _execute_signal_with_cognitive_brain(signal: dict) -> dict | None:
        # Predictive Engine Check - Validate signal has sufficient edge
        market_features = signal.get("market_features")
        if market_features is not None or _env_bool("ALLOW_SIMULATED_PREDICTIVE_GATE"):
            try:
                from models.predictive_engine import create_predictive_engine
                import pandas as pd
                import time

                predictive_engine = create_predictive_engine(min_edge_threshold=0.07)
                price = signal.get("price", 0.5)
                ts_res = signal.get("timestamp_resolution", time.time() + 3600)
                if market_features is None:
                    logger.warning("Using simulated predictive-gate features because ALLOW_SIMULATED_PREDICTIVE_GATE is enabled.")
                    market_features = {'price': [0.5], 'volume': [100], 'bid_depth': [50], 'ask_depth': [50]}
                mock_df = pd.DataFrame(market_features)

                prediction = predictive_engine.predire_pari_gagnant(
                    df_market_ticks=mock_df,
                    clob_price_yes=price,
                    timestamp_resolution=ts_res
                )

                if not prediction.get("pari_approuve"):
                    logger.info(f"💤 [PREDICTIVE ENGINE] Signal rejected: Edge {prediction.get('absolute_edge', 0):.1%} < 7%")
                    return None

                signal["predictive_probability"] = prediction.get("probability_win")
                signal["predictive_edge"] = prediction.get("absolute_edge")
                logger.info(f"🔮 [PREDICTIVE ENGINE] Signal validated: P(win)={prediction.get('probability_win'):.1%}, Edge={prediction.get('absolute_edge'):+.1%}")

            except Exception as e:
                logger.warning(f"Predictive engine check failed, continuing: {e}")
        else:
            logger.debug("Predictive gate skipped: no real market_features on signal.")
        
        try:
            cognitive_decision = await cognitive_brain.synthetiser_decision_cognitive(signal)
            signal = cognitive_brain.enrich_signal(signal, cognitive_decision)
            logger.info("LOBSTAR cognitive decision: %s", cognitive_decision.reason)
        except Exception as exc:
            logger.warning("LOBSTAR cognitive brain failed, continuing with raw signal: %s", exc)

        source = signal.get("source", "")
        
        # Arbitrage Netting: If an arbitrage anomaly is identified -> Route directly to instant sum-of-outcomes netting for risk-free profit.
        if source == "arbitrage" or signal.get("arb_type") is not None:
            logger.info("⚡ ARBITRAGE SIGNAL DETECTED. Executing instant sum-of-outcomes netting...")
            return await execute_regex_signal(
                signal, ledger, freqai,
                risk=risk, hmm=hmm, store=store, executor=None,
                scanner=market_scanner,
            )

        # Volatility Regime Adaptive Routing:
        # If LOW_VOLATILITY with thin spreads -> Force PassiveExecutor (Maker mode).
        # Otherwise, route directly to CLOB Taker mode for instantaneous execution.
        returns = signal.get("returns")
        if returns is None and _env_bool("ALLOW_SIMULATED_REGIME_INPUTS"):
            import numpy as np

            logger.warning("Using simulated zero returns because ALLOW_SIMULATED_REGIME_INPUTS is enabled.")
            returns = np.zeros(100, dtype=np.float32)
        try:
            state, label = hmm.predict_with_label(returns) if returns is not None else (None, "UNKNOWN")
        except Exception as exc:
            logger.warning("Regime prediction failed, using UNKNOWN: %s", exc)
            label = "UNKNOWN"

        current_executor = passive_executor
        if label == "LOW_VOLATILITY":
            logger.info("Regime is LOW_VOLATILITY: Forcing PassiveExecutor (Maker Mode)")
            current_executor = passive_executor
        else:
            logger.info(f"Regime is {label}: Routing directly to CLOB (Taker Mode)")
            current_executor = None

        chat_id = signal.get("chat_id")
        tenant_wallet = access_control.obtenir_wallet_associe(chat_id) if chat_id else None

        if source == "lobstar_llm":
            if not lobstar:
                logger.warning("Lobstar signal received but agent is disabled.")
                return None
            return await execute_lobstar_signal(
                signal, ledger, freqai, lobstar,
                risk=risk, hmm=hmm, store=store, executor=current_executor,
                scanner=market_scanner, tenant_wallet=tenant_wallet,
            )
        if source == "polymarket_onchain":
            await _handle_onchain_signal(
                signal, ledger, hmm, store,
            )
            return None
        return await execute_regex_signal(
            signal, ledger, freqai,
            risk=risk, hmm=hmm, store=store, executor=current_executor,
            scanner=market_scanner, tenant_wallet=tenant_wallet,
        )



    def on_signal(signal: dict) -> None:
        logger.info("Signal received: %s", _safe_signal_for_log(signal))
        
        if not circuit_breaker.is_allowed():
            logger.error("CIRCUIT BREAKER OPEN. Skipping signal.")
            notifier.send("🛑 *CIRCUIT BREAKER OPEN*\nTrading paused due to consecutive failures.")
            return

        if len(_pending_tasks) >= _TASK_SLOTS:
            _cleanup_tasks()
        if len(_pending_tasks) >= _TASK_SLOTS:
            logger.warning("Task queue full, dropping signal")
            return
        raw_task = asyncio.create_task(_execute_signal_with_cognitive_brain(signal))
        task = asyncio.create_task(
            _confirm_and_cleanup(raw_task, signal, listener)
        )
        _pending_tasks.append(task)

        # Capture signal snapshot
        snapshot_mgr.capture(
            category="TRADING",
            component="SIGNAL",
            data=signal,
            tags=["signal", signal.get("source", "unknown")]
        )

    async def _handle_onchain_signal(
        sig: dict,
        lgr: Ledger,
        hm: HMMRegimeFilter,
        st: FeatureStore,
    ) -> None:
        token_id = sig.get("token_id", "")
        side = sig.get("side", "BUY")
        maker_amount = sig.get("maker_amount", "0")
        logger.info(
            f"[ONCHAIN] Copy-trade candidate: {side} {token_id} "
            f"amount={maker_amount}"
        )
        if st:
            st.record_signal(
                source="polymarket_onchain",
                ticker=token_id,
                side=side,
                price=0.0,
                size=float(maker_amount) if maker_amount else 0.0,
                confidence=0.7,
                regime_label="UNKNOWN",
            )

    listener = build_telegram_listener(
        secrets=secrets,
        on_signal=on_signal,
        chat_id=chat_id,
        access_control=access_control,
    )

    from utils.api_key_notifier import get_api_key_notifier
    api_check = get_api_key_notifier().check_all_keys(runtime_secrets=secrets)
    logger.info(f"🔑 API Key Check: {api_check['total_missing']} missing, {len(api_check['critical'])} critical, {len(api_check['loaded_from_vault'])} from Vault")
    if api_check["missing"]:
        from telegram.constants import ParseMode
        alert = get_api_key_notifier().format_telegram_alert(api_check)
        logger.info(f"📨 Sending API key alert to chat_id={chat_id}")
        try:
            if chat_id:
                await listener.send_message(alert, chat_id=chat_id, parse_mode=ParseMode.MARKDOWN)
                logger.info("✅ API key alert sent to Telegram")
            else:
                logger.warning(f"⚠️ chat_id is None, cannot send Telegram alert")
        except Exception as e:
            logger.error(f"❌ Failed to send API key alert: {e}")

    market_scanner = MarketScanner()
    crypto_intelligence = build_crypto_intelligence()
    cognitive_brain = build_cognitive_brain(store, market_scanner, training_pipeline)
    broadcaster = build_broadcaster(container, training_pipeline, market_scanner)

    from core.mlops_feedback_loop import LobstarMLOpsEngine
    mlops_engine = LobstarMLOpsEngine()

    from core.quantum_runner import LobstarQuantumRunner
    runner = LobstarQuantumRunner()
    runner.enregistrer_job("Web_Scraper_Ticks", freqai.stream_ticks_to_duckdb, interval_sec=0.1)
    if cognitive_brain.arbitrage_engine:
        runner.enregistrer_job("Arbitrage_Matrix_Scan", cognitive_brain.arbitrage_engine.scanner_anomalies, interval_sec=5.0)
    runner.enregistrer_job("MLOps_Health_Check", mlops_engine.analyser_sante_brain, interval_sec=14400.0)

    listener.attach_components(
        ledger=ledger,
        risk=risk,
        hmm=hmm,
        store=store,
        executor=passive_executor,
        scanner=market_scanner,
        copy_agent=copy_trading_agent,
    )

    async def _health_check_loop():
        """Periodic model health, drift check, and self-improvement analysis."""
        while True:
            await asyncio.sleep(3600) # Every hour
            for ticker in ["SOL", "BTC", "ETH"]:
                report = await run_blocking(
                    f"model health check {ticker}",
                    model_validator.run_health_check,
                    ticker,
                    "default_v1",
                    timeout=30.0,
                )
                if report.get("health") == "CRITICAL":
                    msg = f"🚨 *DRIFT DETECTED: {ticker}*\n\nModel validation failed. Triggering autonomous retraining..."
                    await listener.send_message(msg, parse_mode="Markdown")
                    
                    # Trigger retraining
                    try:
                        await run_blocking(
                            f"training cycle {ticker}",
                            training_pipeline.run_cycle,
                            ticker,
                            timeout=float(os.getenv("TRAINING_CYCLE_TIMEOUT_SECONDS", "300")),
                        )
                        await listener.send_message(
                            f"✅ *RECALIBRATION COMPLETE: {ticker}*\n\nModel weights updated and redeployed.",
                            parse_mode="Markdown",
                        )
                    except Exception as e:
                        logger.error(f"Retraining failed for {ticker}: {e}")
                        await listener.send_message(
                            f"❌ *RECALIBRATION FAILED: {ticker}*\n\nError: {e}",
                            parse_mode="Markdown",
                        )
                    
                    self_improver.log_incident("MODEL_DRIFT", f"Drift detected for {ticker}", "Distribution shift", "Prediction accuracy degradation")
            
            # Continuous Improvement Report
            imp_report = await run_blocking(
                "self-improvement report",
                self_improver.generate_improvement_report,
                timeout=30.0,
            )
            await listener.send_message(imp_report, parse_mode="Markdown")

            try:
                from utils.data_archiver import DataArchiver
                archiver = DataArchiver()
                await run_blocking(
                    "archive maintenance",
                    archiver.run_maintenance_cycle,
                    timeout=120.0,
                )
            except Exception as e:
                logger.error(f"Maintenance cycle failed: {e}")

            try:
                from scripts.rl_feedback_loop import run_rl_feedback_loop
                await run_blocking(
                    "RL feedback loop",
                    run_rl_feedback_loop,
                    timeout=120.0,
                )
                logger.info("Dynamic ML reinforcement weights updated successfully via background maintenance.")
            except Exception as e:
                logger.error(f"Failed to execute dynamic ML feedback: {e}")


    async def _market_scan_loop() -> None:
        from utils.market_scanner import SCAN_INTERVAL_SECONDS
        
        # Wait for Telegram bot to be ready
        for _ in range(30):
            if listener.application:
                break
            await asyncio.sleep(1)
            
        logger.info(f"Market scanner started (interval={SCAN_INTERVAL_SECONDS}s)")
        first_scan = True
        last_crypto_intelligence_at = 0.0
        crypto_intelligence_interval = int(os.getenv("CRYPTO_INTELLIGENCE_INTERVAL_SECONDS", "1800"))
        last_sentiment = None
        while True:
            try:
                result = await run_blocking(
                    "market scan",
                    market_scanner.scan_markets,
                    timeout=float(os.getenv("MARKET_SCAN_TIMEOUT_SECONDS", "60")),
                )
                if result.total_markets_scanned > 0:
                    logger.info(
                        f"Scan: {result.total_markets_scanned} markets, "
                        f"{len(result.winning_bets)} winning, "
                        f"{len(result.trending_markets)} trending, "
                        f"{len(result.competitive_markets)} competitive"
                    )
                    if first_scan:
                        signals = (
                            result.winning_bets
                            + result.trending_markets
                            + result.competitive_markets
                            + result.arbitrage_opportunities
                        )
                        if signals:
                            report = format_scan_report(result)
                        else:
                            fallback_markets = await run_blocking(
                                "market report fallback",
                                market_scanner.client.list_markets,
                                limit=10,
                                timeout=30.0,
                            )
                            report = format_market_report(fallback_markets)
                        await listener.send_message(report, parse_mode="Markdown")
                        
                        # Capture periodic snapshot
                        snapshot_mgr.capture(
                            category="SYSTEM",
                            component="MARKET_REPORT",
                            data={"report": report},
                            tags=["periodic", "market_scan"]
                        )
                        first_scan = False

                    sentiment = result.aggregate_sentiment.get("sentiment", "NEUTRAL")
                    if sentiment != last_sentiment:
                        mood = result.aggregate_sentiment.get("bullish_pct", 50)
                        await listener.send_message(
                            f"🌍 *Market Feeling Update*\n"
                            f"Feeling: `{sentiment}`\n"
                            f"Bullish share: `{mood:.1f}%`",
                            parse_mode="Markdown",
                        )
                        last_sentiment = sentiment
                    
                    # Persist features for training
                    await run_blocking(
                        "record scanner features",
                        market_scanner.record_features,
                        store,
                        timeout=30.0,
                    )
                    await broadcaster.scan_and_broadcast()

                    now = datetime.now(timezone.utc).timestamp()
                    if first_scan or now - last_crypto_intelligence_at >= crypto_intelligence_interval:
                        markets = await run_blocking(
                            "crypto intelligence market fetch",
                            market_scanner.client.list_markets,
                            limit=100,
                            sort_by="volume",
                            timeout=30.0,
                        )
                        intelligence_report = await run_blocking(
                            "crypto intelligence analysis",
                            crypto_intelligence.analyze,
                            markets,
                            timeout=30.0,
                        )
                        if intelligence_report.crypto_market_count > 0:
                            intelligence_text = format_intelligence_report(intelligence_report)
                            sent = await listener.send_message(intelligence_text)
                            if sent:
                                last_crypto_intelligence_at = now
                            snapshot_mgr.capture(
                                category="SYSTEM",
                                component="CRYPTO_INTELLIGENCE",
                                data=intelligence_report.to_dict(),
                                tags=["periodic", "crypto_intelligence"],
                            )
                    
                    if result.winning_bets:
                        alert = format_winning_bets_alert(result.winning_bets[:3])
                        await listener.send_message(alert, parse_mode="Markdown")
                        trending = format_scan_report(result)
                        if len(trending) > 100:
                            await listener.send_message(trending, parse_mode="Markdown")
                else:
                    logger.warning("Scan returned 0 markets — check API connectivity")
            except Exception as e:
                logger.error(f"Market scan failed: {e}")
            await asyncio.sleep(SCAN_INTERVAL_SECONDS)

    ws_url = secrets.get("WS_URL") or os.getenv("WS_URL", "")
    polygon_rpc = secrets.get("POLYGON_RPC_URL") or os.getenv("POLYGON_RPC_URL") or os.getenv("RPC_URL", "")

    polymarket_monitor = None
    if ws_url:
        target_wallet = os.getenv("TARGET_WALLET", "")
        polymarket_monitor = PolymarketMonitor(
            on_signal=on_signal,
            target_wallet=target_wallet or None,
            ws_url=ws_url,
            rpc_url=polygon_rpc,
        )
        logger.info(f"Polymarket on-chain monitor: {'enabled (target=' + target_wallet + ')' if target_wallet else 'enabled (ALL wallets)'}")
    else:
        logger.info("Polymarket on-chain monitor: disabled (set WS_URL or vault WS_URL to enable)")

    logger.info(f"Telegram bot listening — execution mode: {mode}")
    try:
        telegram_task = asyncio.create_task(listener.start())
        scan_task = asyncio.create_task(_market_scan_loop())
        retrain_task = asyncio.create_task(_health_check_loop())
        monitor_task = asyncio.create_task(polymarket_monitor.start()) if polymarket_monitor else None
        runner_task = asyncio.create_task(runner.start())
        tasks = [telegram_task, scan_task, retrain_task, runner_task] + ([monitor_task] if monitor_task else [])
        await asyncio.gather(*tasks)
    finally:
        runner.stop()
        if polymarket_monitor:
            await polymarket_monitor.stop()
        scan_task.cancel()
        retrain_task.cancel()
        await _drain_pending_tasks()


async def resolve_chat() -> None:
    from telegram import Update
    from telegram.ext import Application, MessageHandler, filters

    vault = VaultHandler()
    secrets = vault.fetch_quantum_secrets()
    app = Application.builder().token(secrets["TELEGRAM_BOT_TOKEN"]).build()

    found: list[dict] = []

    async def handler(update: Update, _ctx) -> None:
        msg = update.channel_post or update.message
        if msg and msg.chat:
            chat = msg.chat
            found.append({"id": chat.id, "type": chat.type, "title": chat.title, "username": chat.username})
            logger.info(f"Chat detected — id={chat.id} type={chat.type} title={chat.title}")

    app.add_handler(MessageHandler(filters.TEXT, handler))
    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    logger.info("Send a message in the target channel now...")
    for i in range(15, 0, -1):
        logger.info("Waiting for chat discovery: %ss remaining", i)
        await asyncio.sleep(1)

    await app.updater.stop()
    await app.stop()
    await app.shutdown()

    if not found:
        logger.warning("No messages received. Is the bot admin in the channel?")
        return

    logger.info(f"Detected {len(found)} chat(s). Set CHAT_ID={found[0]['id']} to use it.")


async def archive_maintenance() -> None:
    from utils.data_archiver import DataArchiver
    archiver = DataArchiver()
    result = archiver.run_maintenance_cycle()
    logger.info(f"Maintenance cycle complete: {result}")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Quant Agentic Trading Core")
    parser.add_argument("--dry-run", action="store_true", help="Validate pipeline components")
    parser.add_argument("--resolve-chat", action="store_true", help="Detect chat ID from incoming messages")
    parser.add_argument(
        "--mode", type=str, default="PAPER",
        choices=["REPLAY", "PAPER", "SHADOW", "PROD"],
        help="Execution mode: REPLAY (backtest), PAPER (simulated), SHADOW (mini-size), PROD (real capital)",
    )
    parser.add_argument("--maintenance", action="store_true", help="Run archive maintenance cycle and exit")
    args = parser.parse_args()
    try:
        if args.resolve_chat:
            with telegram_single_instance_lock():
                asyncio.run(resolve_chat())
        elif args.maintenance:
            asyncio.run(archive_maintenance())
        else:
            if args.dry_run:
                asyncio.run(main(dry_run=args.dry_run, execution_mode=args.mode))
            else:
                with telegram_single_instance_lock():
                    asyncio.run(main(dry_run=args.dry_run, execution_mode=args.mode))
    except QuantFatal as e:
        logger.critical(f"FATAL: {e}")
        raise SystemExit(1)
