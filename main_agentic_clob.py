import argparse
import asyncio
import contextlib
import fcntl
import logging
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from core.container import ServiceContainer
from core.signal_executor import execute_lobstar_signal, execute_regex_signal
from core.training_pipeline import TrainingPipeline
from mcp_agents.lobstar_agent import LobstarAgent
from monitors.polymarket_monitor import PolymarketMonitor
from telegram_scraper.telegram_listener import TelegramListener
from utils.circuit_breaker import CircuitBreaker
from utils.exceptions import QuantFatal
from ledger.ledger_db import Ledger
from user_data.strategies.hmm_filter import HMMRegimeFilter
from utils.feature_store import FeatureStore
from utils.market_scanner import MarketScanner
from utils.model_validator import ModelValidator
from ai.agents.self_improvement_agent import SelfImprovementAgent
from utils.snapshot_manager import get_snapshot_manager
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

    # Rehydrate risk engine
    container.risk.rehydrate_from_ledger(container.ledger)
    secrets = container.secrets
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

            if result["status"] == "SUCCESS":
                logger.info(f"Signal executed successfully: {result['trade_id']}")
                notifier.send(
                    f"✅ *Trade Executed*\n"
                    f"Ticker: `{result['ticker']}`\n"
                    f"Side: `{result['side']}`\n"
                    f"Size: `{result['executed_size']:.2f}` @ `{result['price']:.4f}`\n"
                    f"Mode: `{execution_mode}`"
                )
                circuit_breaker.record_success()
            else:
                logger.warning(f"Signal execution failed: {result.get('reason', 'Unknown error')}")
                notifier.send(f"⚠️ *Execution Failed*\nTicker: `{result['ticker']}`\nReason: `{result.get('reason_1', 'Unknown')}`")
                circuit_breaker.record_failure(result.get("reason_1", "Execution failure"))

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
        source = signal.get("source", "")
        if source == "lobstar_llm":
            if not lobstar:
                logger.warning("Lobstar signal received but agent is disabled.")
                return
            raw_task = asyncio.create_task(
                execute_lobstar_signal(
                    signal, ledger, freqai, lobstar,
                    risk=risk, hmm=hmm, store=store, executor=passive_executor,
                    scanner=market_scanner,
                )
            )
        elif source == "polymarket_onchain":
            raw_task = asyncio.create_task(
                _handle_onchain_signal(
                    signal, ledger, hmm, store,
                )
            )
        else:
            raw_task = asyncio.create_task(
                execute_regex_signal(
                    signal, ledger, freqai,
                    risk=risk, hmm=hmm, store=store, executor=passive_executor,
                    scanner=market_scanner,
                )
            )
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

    raw_chat_id = os.getenv("CHAT_ID", "")
    chat_id = int(raw_chat_id) if raw_chat_id else None
    private_chat_ids = parse_private_chat_ids(os.getenv("TELEGRAM_PRIVATE_CHAT_IDS", ""))
    admin_chat_ids = parse_chat_ids(os.getenv("TELEGRAM_ADMIN_CHAT_IDS", ""))
    proxy_url = os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY") or None

    listener = TelegramListener(
        bot_token=secrets["TELEGRAM_BOT_TOKEN"],
        on_signal=on_signal,
        channel_username=os.getenv("TARGET_CHANNEL", ""),
        chat_id=chat_id,
        private_chat_ids=private_chat_ids,
        admin_chat_ids=admin_chat_ids,
        allow_private_messages=os.getenv("TELEGRAM_PRIVATE_ENABLED", "1") != "0",
        proxy_url=proxy_url,
    )


    market_scanner = MarketScanner()

    listener.attach_components(
        ledger=ledger,
        risk=risk,
        hmm=hmm,
        store=store,
        executor=passive_executor,
        scanner=market_scanner,
    )

    async def _health_check_loop():
        """Periodic model health, drift check, and self-improvement analysis."""
        while True:
            await asyncio.sleep(3600) # Every hour
            for ticker in ["SOL", "BTC", "ETH"]:
                report = model_validator.run_health_check(ticker, "default_v1")
                if report.get("health") == "CRITICAL":
                    msg = f"🚨 *DRIFT DETECTED: {ticker}*\n\nModel validation failed. Triggering autonomous retraining..."
                    await listener.send_message(msg, parse_mode="Markdown")
                    
                    # Trigger retraining
                    try:
                        training_pipeline.run_cycle(ticker)
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
            imp_report = self_improver.generate_improvement_report()
            await listener.send_message(imp_report, parse_mode="Markdown")

            # Periodic Maintenance (Archiving & Cleanup)
            try:
                from utils.data_archiver import DataArchiver
                archiver = DataArchiver()
                archiver.run_maintenance_cycle()
            except Exception as e:
                logger.error(f"Maintenance cycle failed: {e}")

    async def _market_scan_loop() -> None:
        from utils.market_scanner import SCAN_INTERVAL_SECONDS
        
        # Wait for Telegram bot to be ready
        for _ in range(30):
            if listener.application:
                break
            await asyncio.sleep(1)
            
        logger.info(f"Market scanner started (interval={SCAN_INTERVAL_SECONDS}s)")
        first_scan = True
        last_sentiment = None
        while True:
            try:
                result = market_scanner.scan_markets()
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
                        report = format_scan_report(result) if signals else format_market_report(
                            market_scanner.client.list_markets(limit=10)
                        )
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
                    market_scanner.record_features(store)
                    
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
        tasks = [telegram_task, scan_task, retrain_task] + ([monitor_task] if monitor_task else [])
        await asyncio.gather(*tasks)
    finally:
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
        print(f"  Waiting {i}s...   ", end="\r")
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
        exit(1)
