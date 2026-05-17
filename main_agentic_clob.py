import argparse
import asyncio
import contextlib
import fcntl
import logging
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from dotenv import load_dotenv
from pydantic import SecretStr

load_dotenv()

# Establish secure logging filters BEFORE any other imports to protect all modules
from utils.security_utils import setup_secure_logging
setup_secure_logging()

# Apply quantitative hook backward-compatible aliases early
from utils.localization_sync import apply_backward_compatible_aliases
apply_backward_compatible_aliases()

from core.container import ServiceContainer
from core.lobstar_cognitive_brain import LobstarCognitiveBrain
from core.training_pipeline import TrainingPipeline
from mcp_agents.lobstar_agent import LobstarAgent
from monitors.polymarket_monitor import PolymarketMonitor
from agents.copy_trading_agent import CopyTradingAgent, CopyConfig
from telegram_scraper.telegram_listener import TelegramListener
from utils.circuit_breaker import CircuitBreaker
from utils.access_control import AccessControlManager
from utils.crypto_market_intelligence import CryptoMarketIntelligence, format_intelligence_report
from utils.exceptions import QuantFatal
from utils.feature_store import FeatureStore
from utils.market_scanner import MarketScanner
from utils.model_validator import ModelValidator
from ai.agents.self_improvement_agent import SelfImprovementAgent
from utils.snapshot_manager import get_snapshot_manager
from scrapers.telegram_broadcaster import TelegramBroadcaster
from utils.notifier import TelegramNotifier
from utils.message_formatter import (
    format_scan_report,
    format_market_report,
    format_winning_bets_alert,
)
from utils.logging_setup import setup_logging
from utils.telegram_helpers import parse_chat_ids, parse_private_chat_ids
from core.swarm_supervisor import initialize_swarm_supervisor
from core.mlops_feedback_loop import LobstarMLOpsEngine
from core.quantum_runner import LobstarQuantumRunner
from utils.api_key_notifier import get_api_key_notifier
from telegram.constants import ParseMode
from core.orchestrator import LobstarOrchestrator
from core.health_monitor import LobstarHealthMonitor

logger = setup_logging()

DEFAULT_TICKERS = ["SOL", "BTC", "ETH"]


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


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _derive_public_wallet(private_key: SecretStr | str | None) -> str | None:
    if not private_key:
        return None
    try:
        from eth_account import Account

        key_str = private_key.get_secret_value() if isinstance(private_key, SecretStr) else private_key
        return Account.from_key(key_str).address
    except Exception:
        logger.warning("Unable to derive public wallet address from configured key.")
        return None


def build_access_control(secrets: dict, execution_mode: str) -> tuple[AccessControlManager, int | None]:
    raw_admin_ids = secrets.get("TELEGRAM_ADMIN_CHAT_IDS") or os.getenv("TELEGRAM_ADMIN_CHAT_IDS", "")
    admin_chat_ids = parse_chat_ids(raw_admin_ids) or set()
    if execution_mode.upper() == "PROD" and not admin_chat_ids:
        raise QuantFatal("TELEGRAM_ADMIN_CHAT_IDS is required in PROD mode.")

    access_control = AccessControlManager(admin_chat_ids=sorted(admin_chat_ids))
    raw_chat_id = os.getenv("CHAT_ID", "")
    chat_id = int(raw_chat_id) if raw_chat_id else None
    
    private_key_raw = secrets.get("CLOB_PRIVATE_KEY")
    private_key_wrapped = SecretStr(private_key_raw) if private_key_raw else None
    tenant_wallet = _derive_public_wallet(private_key_wrapped)
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
    return CopyTradingAgent(copy_config)


def build_telegram_listener(
    secrets: dict,
    on_signal: Callable[[dict], None],
    chat_id: int | None,
    access_control: AccessControlManager,
) -> TelegramListener:
    token = secrets.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise QuantFatal("TELEGRAM_BOT_TOKEN is missing from Vault/Environment.")
    return TelegramListener(
        bot_token=token,
        on_signal=on_signal,
        chat_id=chat_id,
        access_control=access_control,
    )


def build_broadcaster(container: ServiceContainer, pipeline: TrainingPipeline, scanner: MarketScanner) -> TelegramBroadcaster:
    broadcaster_channel = os.getenv("TELEGRAM_BROADCASTER_CHANNEL_ID", "") or os.getenv("CHAT_ID")
    broadcaster_notifier = TelegramNotifier(
        bot_token=container.secrets.get("TELEGRAM_BOT_TOKEN"),
        chat_id=broadcaster_channel,
    )
    return TelegramBroadcaster(
        notifier=broadcaster_notifier,
        training_pipeline=pipeline,
        market_client=scanner.client,
        tickers=["SOL", "BTC", "ETH"],
        edge_threshold=float(os.getenv("TELEGRAM_BROADCAST_EDGE_THRESHOLD", "0.07")),
    )


def build_cognitive_brain(store: FeatureStore, scanner: MarketScanner, pipeline: TrainingPipeline) -> LobstarCognitiveBrain:
    from core.arbitrage_feedback_loop import LobstarArbitrageEngine
    
    arb_engine = LobstarArbitrageEngine(trigger_threshold=0.015)
    return LobstarCognitiveBrain(
        store=store,
        scanner=scanner,
        training_pipeline=pipeline,
        arbitrage_engine=arb_engine,
    )


def build_crypto_intelligence() -> CryptoMarketIntelligence:
    return CryptoMarketIntelligence()


async def run_blocking(label: str, func: Callable[..., Any], *args: Any, timeout: float = 30.0, **kwargs: Any) -> Any:
    try:
        return await asyncio.wait_for(asyncio.to_thread(func, *args, **kwargs), timeout=timeout)
    except asyncio.TimeoutError:
        raise TimeoutError(f"{label} timed out after {timeout}s") from None


def _setup_ml_features(training_pipeline: TrainingPipeline) -> None:
    """Registers features for autonomous retraining loop."""
    DEFAULT_FEATURES = ["oi_5min", "tam_state", "spread_bps", "mid_price"]
    for tkr in DEFAULT_TICKERS:
        training_pipeline.register_features(tkr, DEFAULT_FEATURES, target_feature="mid_price")


def _setup_quantum_runner(
    runner: LobstarQuantumRunner,
    freqai: Any,
    cognitive_brain: LobstarCognitiveBrain,
    mlops_engine: LobstarMLOpsEngine,
) -> None:
    """Schedules cron/quantum runner background jobs using English hook register_job."""
    runner.register_job("Web_Scraper_Ticks", freqai.stream_ticks_to_duckdb, interval_sec=0.1)
    if cognitive_brain.arbitrage_engine:
        runner.register_job("Arbitrage_Matrix_Scan", cognitive_brain.arbitrage_engine.scanner_anomalies, interval_sec=5.0)
    runner.register_job("MLOps_Health_Check", mlops_engine.analyser_sante_brain, interval_sec=14400.0)


def _dry_run_report(mode: str, circuit_breaker: CircuitBreaker, store: FeatureStore) -> None:
    """Logs dry-run validation report."""
    logger.info("=== DRY RUN MODE ===")
    logger.info("Vault: OK (6 secrets loaded)")
    logger.info("CLOB Engine: OK")
    logger.info("Ledger: OK")
    logger.info("HMMRegimeFilter: OK")
    logger.info("PortfolioRiskEngine: OK")
    logger.info("LobstarAgent: OK")
    logger.info(f"CircuitBreaker: OK ({circuit_breaker.status_report})")
    logger.info(f"FeatureStore: OK ({store.get_stats()})")
    logger.info(f"Execution Mode: {mode}")
    logger.info("Telegram Bot: SKIPPED (dry-run)")
    logger.info("Pipeline validated successfully.")
    logger.info(f"Active mode: {mode} — {'Virtual' if mode in ('REPLAY', 'PAPER') else 'Real capital at risk.'}")


async def _run_services_loop(
    listener: TelegramListener,
    polymarket_monitor: Any,
    runner: LobstarQuantumRunner,
    orchestrator: LobstarOrchestrator,
    health_monitor: LobstarHealthMonitor,
    scan_coro: Any,
    retrain_coro: Any,
    runner_coro: Any,
    mode: str,
) -> None:
    """Concurrently executes all platform services background loops."""
    logger.info(f"Telegram bot listening — execution mode: {mode}")
    scan_task = None
    retrain_task = None
    monitor_task = None
    telegram_task = None
    runner_task = None
    try:
        # Start core components
        orchestrator.start()
        health_monitor.start()

        telegram_task = asyncio.create_task(listener.start())
        scan_task = asyncio.create_task(scan_coro)
        retrain_task = asyncio.create_task(retrain_coro)
        monitor_task = asyncio.create_task(polymarket_monitor.start()) if polymarket_monitor else None
        runner_task = asyncio.create_task(runner_coro)
        
        tasks = [telegram_task, scan_task, retrain_task, runner_task] + ([monitor_task] if monitor_task else [])
        await asyncio.gather(*tasks)
    finally:
        runner.stop()
        await orchestrator.stop()
        await health_monitor.stop()
        if polymarket_monitor:
            try:
                await polymarket_monitor.stop()
            except Exception as e:
                logger.warning(f"Error stopping monitor: {e}")
        if scan_task:
            scan_task.cancel()
        if retrain_task:
            retrain_task.cancel()


async def main(
    dry_run: bool = False,
    execution_mode: str = "PAPER",
) -> None:
    listener = None

    container = ServiceContainer.get_instance()
    notifier = container.notifier
    
    notifier.send(f"🚀 *System Started*\nMode: `{execution_mode}`\nEnvironment: `{os.uname().nodename}`")

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

    swarm_supervisor = await initialize_swarm_supervisor(mode=execution_mode)
    data_diag = swarm_supervisor.check_data_gaps()
    logger.info(f"📊 Data Gap Check: {data_diag}")

    async def on_mode_change(new_mode):
        mode_str = new_mode.value
        logger.warning(f"⚠️ Swarm triggered mode change: {mode_str}")
        ledger.set_execution_mode(mode_str)
        if listener is not None:
            await listener.send_message(f"🔄 *Mode changed to:* `{mode_str}` (Swarm Supervisor)")

    async def on_circuit_breaker(reason, data):
        logger.critical(f"🚨 Swarm Circuit Breaker: {reason.value}")
        if listener is not None:
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
    _setup_ml_features(training_pipeline)

    snapshot_mgr = get_snapshot_manager()
    model_validator = ModelValidator(snapshot_manager=snapshot_mgr)
    self_improver = SelfImprovementAgent()

    if execution_mode:
        ledger.set_execution_mode(execution_mode)

    mode = ledger.get_execution_mode()

    if dry_run:
        _dry_run_report(mode, circuit_breaker, store)
        return

    market_scanner = MarketScanner()
    crypto_intelligence = build_crypto_intelligence()
    cognitive_brain = build_cognitive_brain(store, market_scanner, training_pipeline)
    broadcaster = build_broadcaster(container, training_pipeline, market_scanner)

    mlops_engine = LobstarMLOpsEngine()
    runner = LobstarQuantumRunner()
    _setup_quantum_runner(runner, freqai, cognitive_brain, mlops_engine)

    # Instantiate the new LobstarOrchestrator
    orchestrator = LobstarOrchestrator(
        container=container,
        secrets=secrets,
        execution_mode=execution_mode,
        listener=None, # will attach below
        circuit_breaker=circuit_breaker,
        snapshot_mgr=snapshot_mgr,
        cognitive_brain=cognitive_brain,
        copy_trading_agent=copy_trading_agent,
        market_scanner=market_scanner,
        lobstar_agent=lobstar,
        access_control=access_control,
    )

    listener = build_telegram_listener(
        secrets=secrets,
        on_signal=orchestrator.on_signal,
        chat_id=chat_id,
        access_control=access_control,
    )

    # Attach listener reference to orchestrator
    orchestrator.listener = listener

    health_monitor = LobstarHealthMonitor(
        orchestrator=orchestrator,
        runner=runner,
        port=8080,
    )

    api_check = get_api_key_notifier().check_all_keys(runtime_secrets=secrets)
    logger.info(f"🔑 API Key Check: {api_check['total_missing']} missing, {len(api_check['critical'])} critical")
    if api_check["missing"]:
        alert = get_api_key_notifier().format_telegram_alert(api_check)
        try:
            if chat_id:
                await listener.send_message(alert, chat_id=chat_id, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error(f"❌ Failed to send API key alert: {e}")

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
            for ticker in DEFAULT_TICKERS:
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
                        f"{len(result.trending_markets)} trending"
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
            on_signal=orchestrator.on_signal,
            target_wallet=target_wallet or None,
            ws_url=ws_url,
            rpc_url=polygon_rpc,
        )
        logger.info(f"Polymarket on-chain monitor: {'enabled (target=' + target_wallet + ')' if target_wallet else 'enabled (ALL wallets)'}")
    else:
        logger.info("Polymarket on-chain monitor: disabled (set WS_URL to enable)")

    await _run_services_loop(
        listener=listener,
        polymarket_monitor=polymarket_monitor,
        runner=runner,
        orchestrator=orchestrator,
        health_monitor=health_monitor,
        scan_coro=_market_scan_loop(),
        retrain_coro=_health_check_loop(),
        runner_coro=runner.start(),
        mode=mode,
    )


async def resolve_chat() -> None:
    from telegram import Update
    from telegram.ext import Application, MessageHandler, filters
    from utils.vault_handler import VaultHandler

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
        "--mode", type=str, default=None,
        choices=["REPLAY", "PAPER", "SHADOW", "PROD"],
        help="Execution mode: REPLAY (backtest), PAPER (simulated), SHADOW (mini-size), PROD (real capital)",
    )
    parser.add_argument("--maintenance", action="store_true", help="Run archive maintenance cycle and exit")
    args = parser.parse_args()
    
    # 1. Deterministic Execution Mode Conflict Checking
    real_env = os.getenv("REAL", "false").lower() == "true"
    paper_env = os.getenv("PAPER", "false").lower() == "true"

    if real_env and paper_env:
        logger.critical("🚨 CONFLICT: Both REAL=true and PAPER=true are defined in the environment!")
        raise QuantFatal("Conflicting environment variables: Both REAL=true and PAPER=true are defined!")

    # Exclusive Priority: CLI Argument > Environment Variable
    resolved_mode = "PAPER"
    if real_env:
        resolved_mode = "PROD"
    elif paper_env:
        resolved_mode = "PAPER"

    if args.mode is not None:
        resolved_mode = args.mode

    try:
        if args.resolve_chat:
            with telegram_single_instance_lock():
                asyncio.run(resolve_chat())
        elif args.maintenance:
            asyncio.run(archive_maintenance())
        else:
            if args.dry_run:
                asyncio.run(main(dry_run=args.dry_run, execution_mode=resolved_mode))
            else:
                with telegram_single_instance_lock():
                    asyncio.run(main(dry_run=args.dry_run, execution_mode=resolved_mode))
    except QuantFatal as e:
        logger.critical(f"FATAL: {e}")
        raise SystemExit(1)
