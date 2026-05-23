from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger("Lifecycle")
from typing import Any

from bootstrap.factories import build_broadcaster, build_telegram_listener
from bootstrap.helpers import _env_bool, run_blocking
from bootstrap.loops import HMMTrainingLoop, MarketScanLoop, ModelDriftAndHealthLoop, SLTPMonitoringLoop
from bootstrap.scheduler import _setup_ml_features, _setup_quantum_runner
from bootstrap.runtime_context import RuntimeContext
from bootstrap.validators import dry_run_report
from core.health_monitor import LobstarHealthMonitor
from core.health_supervisor_agent import HealthSupervisorAgent, HealthSupervisorConfig
from agents.health_monitor_agent import HealthMonitorAgent, HealthMonitorConfig
from core.orchestrator import LobstarOrchestrator
from core.mlops_feedback_loop import LobstarMLOpsEngine
from core.quantum_runner import LobstarQuantumRunner
from utils.api_key_notifier import get_api_key_notifier
from utils.config_loader import get_health_config, validate_required as validate_config_required
from utils.data_archiver import DataArchiver
from utils.clob_feed_utils import extract_live_clob_token_ids
from utils.vault_handler import VaultHandler
from core.container import ServiceContainer
from utils.crypto_market_intelligence import CryptoMarketIntelligence

try:
    from monitoring.polymarket_monitor import PolymarketMonitor
except ModuleNotFoundError:
    PolymarketMonitor = None

try:
    from scrapers.clob_listener import CLOBListener
except ModuleNotFoundError:
    CLOBListener = None

try:
    from scrapers.user_clob_listener import UserCLOBListener
except ModuleNotFoundError:
    UserCLOBListener = None

try:
    from py_clob_client import ApiCreds
except ModuleNotFoundError:
    ApiCreds = None

logger = logging.getLogger("Lifecycle")

async def run_services_loop(
    listener: Any,
    clob_feed_coro: Any,
    user_ws_coro: Any,
    polymarket_monitor: Any,
    health_supervisor: Any,
    health_sidecar: Any,
    runner: Any,
    orchestrator: Any,
    health_monitor: Any,
    scan_coro: Any,
    retrain_coro: Any,
    runner_coro: Any,
    mode: str,
    extra_tasks: list[asyncio.Task] = None,
) -> None:
    scan_task = None
    retrain_task = None
    clob_feed_task = None
    user_ws_task = None
    monitor_task = None
    telegram_task = None
    runner_task = None
    health_supervisor_task = None
    health_sidecar_task = None
    tasks = []
    try:
        orchestrator.start()
        health_monitor.start()
        telegram_task = asyncio.create_task(listener.start())
        clob_feed_task = asyncio.create_task(clob_feed_coro) if clob_feed_coro else None
        user_ws_task = asyncio.create_task(user_ws_coro) if user_ws_coro else None
        scan_task = asyncio.create_task(scan_coro)
        retrain_task = asyncio.create_task(retrain_coro)
        monitor_task = asyncio.create_task(polymarket_monitor.start()) if polymarket_monitor else None
        health_supervisor_task = asyncio.create_task(health_supervisor.start()) if health_supervisor else None
        health_sidecar_task = asyncio.create_task(health_sidecar.run_forever()) if health_sidecar else None
        runner_task = asyncio.create_task(runner_coro)
        tasks = [telegram_task, scan_task, retrain_task, runner_task]
        if clob_feed_task:
            tasks.append(clob_feed_task)
        if user_ws_task:
            tasks.append(user_ws_task)
        if monitor_task:
            tasks.append(monitor_task)
        if health_supervisor_task:
            tasks.append(health_supervisor_task)
        if health_sidecar_task:
            tasks.append(health_sidecar_task)
        if extra_tasks:
            tasks.extend(extra_tasks)
        await asyncio.gather(*tasks)
    finally:
        runner.stop()
        await orchestrator.stop()
        await health_monitor.stop()
        if polymarket_monitor:
            try:
                await polymarket_monitor.stop()
            except Exception:
                pass
        if health_supervisor:
            try:
                health_supervisor.stop()
            except Exception:
                pass
        if health_sidecar:
            try:
                health_sidecar.stop()
            except Exception:
                pass
        tasks_to_cancel = []
        for task in tasks:
            if task and not task.done():
                task.cancel()
                tasks_to_cancel.append(task)
        if tasks_to_cancel:
            await asyncio.gather(*tasks_to_cancel, return_exceptions=True)


@dataclass(slots=True)
class BotLifecycle:
    ctx: RuntimeContext
    execution_mode: str
    _loops: list[Any] = field(default_factory=list)
    _runner: Any | None = None

    async def start(self) -> None:
        context = self.ctx
        listener = None
        container = ServiceContainer.get_instance()
        notifier = context.notifier
        notifier.send(f"🚀 <b>System Started</b>\nMode: <code>{self.execution_mode}</code>\nEnvironment: <code>{os.uname().nodename}</code>")
        ledger = context.ledger
        freqai = context.freqai
        hmm = context.hmm
        risk = context.risk
        store = context.store
        passive_executor = context.passive_executor
        secrets = context.secrets
        access_control = context.access_control
        chat_id = context.chat_id
        lobstar = context.lobstar
        circuit_breaker = context.circuit_breaker
        copy_trading_agent = context.copy_trading_agent
        training_pipeline = context.training_pipeline
        _setup_ml_features(training_pipeline)
        snapshot_mgr = context.snapshot_mgr
        model_validator = context.model_validator
        self_improver = context.self_improver

        # Check if Telegram is disabled (e.g., TUI mode)
        if _env_bool("TELEGRAM_DISABLED", False):
            logger.info("📡 [SYSTEM] Telegram Listener disabled by environment.")
            listener_enabled = False
        else:
            listener_enabled = True

        if self.execution_mode:
            ledger.set_execution_mode(self.execution_mode)
        mode = ledger.get_execution_mode()
        from utils.env_validation import validate_runtime_env
        validate_runtime_env(mode, secrets)
        if mode == "PROD":
            await container.sync_real_capital()
            # New: Reconcile positions to handle fills while bot was offline
            try:
                from core.services.reconciliation_service import PositionReconciliationService
                reconciler = PositionReconciliationService(ledger, self.ctx.secrets.get("POLYMARKET_WALLET_ADDRESS") or self.ctx.secrets.get("EOA_ADDRESS") or self.ctx.secrets.get("WALLET_ADDRESS", ""))
                await reconciler.reconcile()
            except Exception as e:
                logger.error(f"Position reconciliation failed on startup: {e}")

        # Start Prometheus Exporter
        try:
            from monitoring.prometheus_exporter import exporter
            exporter.start()
            exporter.update_mode(self.execution_mode)
        except ImportError:
            logger.warning("Prometheus exporter not available.")

        if False:
            await self.dry_run_report()
            return
        market_scanner = context.market_scanner
        crypto_intelligence = CryptoMarketIntelligence()
        cognitive_brain = context.cognitive_brain
        broadcaster = build_broadcaster(notifier, training_pipeline, market_scanner)
        from core.healing.autonomic_healer import LobstarAutonomicHealer
        autonomic_healer = LobstarAutonomicHealer(log_file_path="logs/pm2-out.log")
        mlops_engine = LobstarMLOpsEngine()
        runner = LobstarQuantumRunner()

        listener = None
        if listener_enabled:
            listener = build_telegram_listener(secrets=secrets, on_signal=None, chat_id=chat_id, access_control=access_control)

        validate_config_required()
        from core.wallet_manager import PolymarketWalletManager
        polygon_rpc = secrets.get("POLYGON_RPC_URL") or secrets.get("RPC_URL", "")
        wallet_mgr = PolymarketWalletManager(vault_handler=container.vault, polygon_rpc_url=polygon_rpc)
        orchestrator = LobstarOrchestrator(
            secrets=secrets,
            execution_mode=self.execution_mode,
            listener=listener,
            circuit_breaker=circuit_breaker,
            snapshot_mgr=snapshot_mgr,
            cognitive_brain=cognitive_brain,
            copy_trading_agent=copy_trading_agent,
            market_scanner=market_scanner,
            ledger=ledger,
            risk=risk,
            store=store,
            notifier=notifier,
            executor=passive_executor,
            hmm=hmm,
            freqai=freqai,
            history=getattr(container, "history", None),
            trade_notifications=getattr(container, "trade_notifications", None),
            metrics_exporter=getattr(container, "metrics_exporter", None),
            lobstar_agent=lobstar,
            access_control=access_control,
            wallet_manager=wallet_mgr,
        )
        _setup_quantum_runner(
            runner,
            freqai,
            cognitive_brain,
            mlops_engine,
            autonomic_healer,
            broadcaster,
            runtime_secrets=secrets,
            feature_store=store,
            ledger=ledger,
            training_pipeline=training_pipeline,
            risk=risk,
            scanner=market_scanner,
            executor=passive_executor,
            orchestrator=orchestrator,
        )
        autonomic_healer.broadcaster = orchestrator.broadcaster
        if listener:
            listener.on_signal = orchestrator.on_signal
        health_monitor = LobstarHealthMonitor(orchestrator=orchestrator, runner=runner, port=8080)
        api_check = get_api_key_notifier().check_all_keys(runtime_secrets=secrets)
        try:
            import psutil
            cpu_usage = psutil.cpu_percent()
            ram_usage = psutil.virtual_memory().percent
        except ImportError:
            cpu_usage = 0.0
            ram_usage = 0.0
        dashboard_msg = (
            f"🦞 <b>LOBSTAR COMMAND CENTER — ONLINE</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🚀 <b>Status</b> : <code>RUNNING</code>\n"
            f"📡 <b>Mode</b> : <code>{self.execution_mode}</code>\n"
            f"💻 <b>System</b> : CPU <code>{cpu_usage}%</code> | RAM <code>{ram_usage}%</code> \n\n"
            f"{get_api_key_notifier().format_telegram_alert(api_check)}"
        )
        _private_admin_ids = sorted(c for c in getattr(listener, 'admin_chat_ids', set()) if c > 0)
        _dashboard_target = _private_admin_ids[0] if _private_admin_ids else (chat_id if chat_id and chat_id > 0 else None)
        if _dashboard_target:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup

            reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("📖 Manuel", callback_data="help_menu"), InlineKeyboardButton("📊 Statut", callback_data="help_page_3")]])

            async def _send_dashboard_when_ready() -> None:
                if not await listener.wait_until_ready(timeout=45.0):
                    logger.warning("Telegram listener did not become ready in time; startup dashboard skipped.")
                    return
                await listener.send_message(
                    dashboard_msg,
                    chat_id=_dashboard_target,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                )
        else:
            _send_dashboard_when_ready = None
        from utils.market_data_reader import MarketDataReader
        market_reader = MarketDataReader(polymarket_client=market_scanner.client)
        order_manager = None
        try:
            from utils.polymarket_order_manager import PolymarketOrderManager
            order_manager = PolymarketOrderManager(wallet_manager=wallet_mgr, private_key=secrets.get("CLOB_PRIVATE_KEY"))
        except Exception:
            pass
        if listener:
            listener.attach_components(ledger=ledger, risk=risk, hmm=hmm, store=store, executor=passive_executor, scanner=market_scanner, copy_agent=copy_trading_agent, market_reader=market_reader, order_manager=order_manager)
            try:
                from utils.pmxt_adapter_service import PMXTAdapterService
                listener._pmxt_service = PMXTAdapterService()
            except Exception as exc:
                logger.warning("PMXT adapter service unavailable: %s", exc)
        clob_listener = None
        live_clob_feed_coro = None
        try:
            top_markets = await run_blocking("prime live clob token ids", market_scanner.client.list_markets, limit=25, sort_by="volume", timeout=30.0)
            live_token_ids = extract_live_clob_token_ids(top_markets)
            if ledger:
                try:
                    open_pos = ledger.get_open_positions()
                    for pos in open_pos:
                        tid = pos.get("ticker")
                        if tid and tid not in live_token_ids:
                            live_token_ids.append(tid)
                except Exception:
                    pass
            if live_token_ids:
                clob_listener = CLOBListener(token_ids=live_token_ids, store=store)
                async def _persist_live_snapshot(snapshot: dict[str, Any]) -> None:
                    snapshot_mgr.capture(category="SYSTEM", component="CLOB_ORDERBOOK", data=snapshot, tags=["live", "clob", snapshot.get("token_id", "unknown")])
                    swarm = getattr(orchestrator, "_swarm", None)
                    if swarm is not None:
                        await swarm.record_market_tick(snapshot)
                    if ledger:
                        ticker = snapshot.get("token_id")
                        mid_price = snapshot.get("mid_price")
                        if ticker and mid_price:
                            open_pos = [p for p in ledger.get_open_positions() if p.get("ticker") == ticker]
                            if open_pos:
                                due = ledger.get_positions_due_for_exit({ticker: mid_price})
                                for pos in due:
                                    asyncio.create_task(_execute_exit(pos))
                async def _execute_exit(pos: dict):
                    ticker = pos.get("ticker", "")
                    pos_id = pos.get("position_id", "")
                    entry = float(pos.get("entry_price", 0.0))
                    exit_p = float(pos.get("exit_price", 0.0))
                    entry_side = pos.get("side", "BUY").upper()
                    exit_side = "SELL" if entry_side == "BUY" else "BUY"
                    size = float(pos.get("size", 0.0))
                    try:
                        exec_res = await passive_executor.execute(ticker=ticker, side=exit_side, price=exit_p, size=size, override_strict_maker=True)
                        if exec_res.get("status") in ("FILLED", "TAKER_FILLED"):
                            ledger.close_position(pos_id, exit_price=exit_p)
                            pnl_pct = ((exit_p - entry) / entry * 100) if entry > 0 else 0.0
                            if listener:
                                await listener.send_message(f"⏹ <b>[FAST-PATH] Position Closed</b>\nTicker: <code>{ticker}</code>\nExit: <code>{exit_p:.4f}</code>\nPnL: <b>{pnl_pct:+.2f}%</b>", parse_mode="HTML")
                    except Exception as e:
                        logger.error(f"Error in fast-path SL/TP execution: {e}")
                live_clob_feed_coro = clob_listener.run(callback=_persist_live_snapshot)
        except Exception as e:
            logger.warning(f"Live CLOB feed disabled: failed to prime token IDs ({e})")
        market_scan_loop = MarketScanLoop(ctx=context, listener=listener, clob_listener=clob_listener, broadcaster=broadcaster, orchestrator=orchestrator, crypto_intelligence=crypto_intelligence)
        hmm_training_loop = HMMTrainingLoop(ctx=context, market_scanner=market_scanner, hmm=hmm)
        sltp_monitoring_loop = SLTPMonitoringLoop(ctx=context, ledger=ledger, passive_executor=passive_executor, listener=listener)
        model_drift_loop = ModelDriftAndHealthLoop(ctx=context, model_validator=model_validator, training_pipeline=training_pipeline, self_improver=self_improver, listener=listener)
        runner.register_job("Model_Health_And_Drift", model_drift_loop.run, interval_sec=14400.0)
        runner.register_job("HMM_Training", hmm_training_loop.run, interval_sec=21600.0)
        runner.register_job("SLTP_Monitoring", sltp_monitoring_loop.run, interval_sec=10.0)
        if listener and getattr(listener, "_pmxt_service", None):
            async def pmxt_monitored_job():
                try:
                    result = await listener._pmxt_service.run_cycle()
                    if result.get("status") == "FAILED":
                        reason = result.get("reason", "Unknown error")
                        logger.error(f"🚨 [PMXT ADAPTER FAILURE] {reason}")
                        if orchestrator and orchestrator.broadcaster:
                            await orchestrator.broadcaster.diffuser_message_au_canal(
                                f"🚨 <b>PMXT ADAPTER FAILURE</b>\n"
                                f"━━━━━━━━━━━━━━━━━━━━\n"
                                f"Reason: <code>{reason}</code>\n"
                                f"<i>Archival chain may be broken. Check polars/pyarrow installation.</i>"
                            )
                except Exception as e:
                    logger.error(f"PMXT job error: {e}")

            runner.register_job(
                "PMXT_Auto_Cycle",
                pmxt_monitored_job,
                interval_sec=float(os.getenv("PMXT_ADAPTER_INTERVAL_SECONDS", "1800")),
            )
        ws_url = secrets.get("WS_URL", "")
        polymarket_monitor = None
        onchain_monitor_enabled = _env_bool("POLYMARKET_ONCHAIN_MONITOR_ENABLED", False)
        if onchain_monitor_enabled and ws_url:
            target_wallet = secrets.get("TARGET_WALLET", "")
            polymarket_monitor = PolymarketMonitor(on_signal=orchestrator.on_signal, target_wallet=target_wallet or None, ws_url=ws_url, rpc_url=polygon_rpc)
        health_supervisor = HealthSupervisorAgent(
            feature_store=store,
            ledger=ledger,
            wallet_manager=__import__("core.wallet_manager", fromlist=["PolymarketWalletManager"]).PolymarketWalletManager(vault_handler=container.vault, polygon_rpc_url=polygon_rpc),
            data_archiver=DataArchiver(
                db_path=os.path.join(os.getenv("DATA_PATH", "data"), "feature_store.duckdb"),
                feature_store=store
            ),
            broadcaster=orchestrator.broadcaster,
            secrets=secrets,
            config=HealthSupervisorConfig(
                staleness_threshold_seconds=float(get_health_config("polymarket_staleness_seconds", 60.0, env_key="MAX_POLYMARKET_STALENESS_SECONDS")),
                memory_warning_mb=float(get_health_config("memory_warning_mb", 1024, env_key="MAX_MEMORY_MB_THRESHOLD")),
                memory_critical_mb=float(get_health_config("memory_critical_mb", 1536)),
                wallet_reconciliation_interval_seconds=300.0,
                maintenance_interval_seconds=86400.0,
                check_interval_seconds=5.0,
                wallet_drift_tolerance_usd=float(get_health_config("wallet_drift_tolerance_usdc", 0.01, env_key="MAX_WALLET_DRIFT_USDC")),
                disk_usage_warning_bytes=5_000_000_000,
                disk_usage_critical_bytes=8_000_000_000
            )
        )
        health_sidecar = HealthMonitorAgent(config=HealthMonitorConfig(heartbeat_interval_seconds=30.0, duckdb_prune_interval_seconds=86400.0, memory_check_interval_seconds=60.0, max_memory_rss_mb=float(get_health_config("memory_warning_mb", 1024, env_key="MAX_MEMORY_MB_THRESHOLD")), enable_ledger_reconciliation=_env_bool("HEALTH_SIDE_CAR_ENABLE_LEDGER_RECONCILIATION", True), enable_feature_store_maintenance=_env_bool("HEALTH_SIDE_CAR_ENABLE_FEATURE_STORE_MAINTENANCE", True)), feature_store=store, ledger=ledger, broadcaster=orchestrator.broadcaster)
        user_ws_coro = None

        # --- Dual-Mode Redis Control Listener ---
        async def redis_mode_listener():
            try:
                import redis.asyncio as aioredis
                import json
                r = aioredis.Redis(host='localhost', port=6379, db=0)
                pubsub = r.pubsub()
                await pubsub.subscribe("lobstar:control:mode")
                logger.info("📡 [REDIS] Listening for hot mode swaps on 'lobstar:control:mode'")

                async for message in pubsub.listen():
                    if message["type"] == "message":
                        data = json.loads(message["data"])
                        if data.get("action") == "SWITCH_MODE":
                            new_mode = data.get("mode")
                            current_mode = ledger.get_execution_mode() if ledger else "UNKNOWN"
                            if new_mode and ledger and current_mode != new_mode:
                                ledger.set_execution_mode(new_mode, manual=True)
                                orchestrator.execution_mode = new_mode
                                self.execution_mode = new_mode
                                msg = f"🔄 <b>[HOT SWAP]</b> Mode d'exécution changé via Redis: <code>{current_mode}</code> ➡️ <code>{new_mode}</code>"
                                logger.warning(msg)
                                if broadcaster and broadcaster.notifier:
                                    await broadcaster.notifier.send_async(msg, parse_mode="HTML")
            except ImportError:
                logger.warning("redis.asyncio not available. Redis hot-swap disabled.")
            except Exception as e:
                logger.debug(f"Redis mode listener error: {e}")

        redis_task = asyncio.create_task(redis_mode_listener())
        dashboard_task = asyncio.create_task(_send_dashboard_when_ready()) if listener and _dashboard_target else None

        # --- Aulekator: Exchange Price Service ---
        from utils.exchange_price_service import ExchangePriceService
        price_service = ExchangePriceService()
        price_task = asyncio.create_task(price_service.start())
        orchestrator.price_service = price_service
        # ----------------------------------------

        if secrets.get("CLOB_API_KEY") and secrets.get("CLOB_API_SECRET") and secrets.get("CLOB_API_PASSPHRASE"):
            try:
                user_creds = ApiCreds(api_key=secrets["CLOB_API_KEY"], api_secret=secrets["CLOB_API_SECRET"], api_passphrase=secrets["CLOB_API_PASSPHRASE"])
                user_listener = UserCLOBListener(api_creds=user_creds)
                async def on_user_event(event: dict):
                    event_type = event.get("event_type")
                    if event_type == "order":
                        if event.get("status") == "CLOSED":
                            logger.info(f"✅ Order {event.get('order_id')} fully filled/closed.")
                    elif event_type == "trade":
                        order_id = event.get("order_id")
                        size = float(event.get("size", 0.0))
                        price = float(event.get("price", 0.0))
                        if ledger:
                            success = ledger.update_position_fill(exchange_order_id=order_id, filled_qty=size, execution_price=price)
                            if success and listener:
                                await listener.send_message(f"⚡ <b>Live Fill Detected</b>\nOrder: <code>{order_id[:8]}...</code>\nSize: <code>{size}</code> @ <code>{price}</code>", parse_mode="HTML")
                user_listener.on_event = on_user_event
                user_ws_coro = user_listener.run()
            except Exception as e:
                logger.error(f"User CLOB listener initialization failed: {e}")
        from utils.data_ingestion import BinanceWSListener
        binance_listener = BinanceWSListener(store=store, tickers=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
        
        # Start binance listener in a background task
        async def run_binance():
            try:
                await binance_listener._run()
            except Exception as e:
                logger.error(f"Binance WS Listener failed: {e}")

        binance_task = asyncio.create_task(run_binance())
        
        extra_tasks = [redis_task, price_task, binance_task]
        if dashboard_task:
            extra_tasks.append(dashboard_task)
        await run_services_loop(listener=listener, clob_feed_coro=live_clob_feed_coro, user_ws_coro=user_ws_coro, polymarket_monitor=polymarket_monitor, health_supervisor=health_supervisor, health_sidecar=health_sidecar, runner=runner, orchestrator=orchestrator, health_monitor=health_monitor, scan_coro=market_scan_loop.run(), retrain_coro=model_drift_loop.run(), runner_coro=runner.start(), mode=mode, extra_tasks=extra_tasks)

    async def dry_run_report(self) -> None:
        await dry_run_report(
            self.execution_mode,
            self.ctx.circuit_breaker,
            self.ctx.store,
            logger=getattr(self.ctx.notifier, "logger", None),
            secrets=self.ctx.secrets,
            vault=ServiceContainer.get_instance().vault,
            freqai=self.ctx.freqai,
            ledger=self.ctx.ledger,
            hmm=self.ctx.hmm,
            risk=self.ctx.risk,
            executor=self.ctx.passive_executor,
            rpc_url=self.ctx.secrets.get("POLYGON_RPC_URL"),
        )

    async def stop(self) -> None:
        logger.info("Stopping BotLifecycle...")
        # Add cleanup logic if needed
        pass
