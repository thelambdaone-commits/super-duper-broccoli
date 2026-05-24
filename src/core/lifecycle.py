from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger("Lifecycle")
from typing import Any

from core.factories import build_broadcaster, build_telegram_listener
from core.helpers import _env_bool, run_blocking
from core.loops import HMMTrainingLoop, MarketScanLoop, ModelDriftAndHealthLoop, SLTPMonitoringLoop
from core.scheduler import _setup_ml_features, _setup_quantum_runner
from core.runtime_context import RuntimeContext
from core.validators import dry_run_report
from core.health_monitor import LobstarHealthMonitor
from core.health_supervisor_agent import HealthSupervisorAgent, HealthSupervisorConfig
from agents.health_monitor_agent import HealthMonitorAgent, HealthMonitorConfig
from core.lifecycle_assembly import (
    attach_listener_runtime_components,
    build_live_clob_feed,
    build_redis_mode_listener,
    build_dashboard_sender,
    build_health_sidecar,
    build_health_supervisor,
    build_user_stream,
    register_runtime_loops,
    start_binance_listener,
    start_price_service,
)
from core.orchestrator import LobstarOrchestrator
from core.mlops_feedback_loop import LobstarMLOpsEngine
from core.quantum_runner import LobstarQuantumRunner
from utils.api_key_notifier import get_api_key_notifier
from utils.config_loader import get_health_config, validate_required as validate_config_required
from utils.vault_handler import VaultHandler
from core.container import ServiceContainer
from utils.crypto_market_intelligence import CryptoMarketIntelligence

try:
    from services.polymarket_monitor import PolymarketMonitor
except ModuleNotFoundError:
    PolymarketMonitor = None

try:
    from polymarket.api.clob_listener import CLOBListener
except ModuleNotFoundError:
    CLOBListener = None

try:
    from polymarket.api.user_clob_listener import UserCLOBListener
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
                from services.reconciliation_service import PositionReconciliationService
                reconciler = PositionReconciliationService(
                    ledger,
                    self.ctx.secrets.get("POLYMARKET_WALLET_ADDRESS") or self.ctx.secrets.get("EOA_ADDRESS") or self.ctx.secrets.get("WALLET_ADDRESS", ""),
                    freqai=freqai
                )
                await reconciler.reconcile()
            except Exception as e:
                logger.error(f"Position reconciliation failed on startup: {e}")

        # Start Prometheus Exporter
        try:
            from services.prometheus_exporter import exporter
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
        from polymarket.execution.wallet_manager import PolymarketWalletManager
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
        _dashboard_target, _send_dashboard_when_ready = build_dashboard_sender(listener, chat_id, dashboard_msg)
        attach_listener_runtime_components(
            listener,
            ledger=ledger,
            risk=risk,
            hmm=hmm,
            store=store,
            executor=passive_executor,
            market_scanner=market_scanner,
            copy_trading_agent=copy_trading_agent,
            wallet_manager=wallet_mgr,
            secrets=secrets,
            runner=runner,
        )
        clob_listener = None
        live_clob_feed_coro = None
        clob_listener, live_clob_feed_coro = await build_live_clob_feed(
            market_scanner=market_scanner,
            ledger=ledger,
            store=store,
            snapshot_mgr=snapshot_mgr,
            orchestrator=orchestrator,
            passive_executor=passive_executor,
            listener=listener,
            clob_listener_cls=CLOBListener,
            run_blocking_fn=run_blocking,
        )
        market_scan_loop = MarketScanLoop(ctx=context, listener=listener, clob_listener=clob_listener, broadcaster=broadcaster, orchestrator=orchestrator, crypto_intelligence=crypto_intelligence)
        hmm_training_loop = HMMTrainingLoop(ctx=context, market_scanner=market_scanner, hmm=hmm)
        sltp_monitoring_loop = SLTPMonitoringLoop(ctx=context, ledger=ledger, passive_executor=passive_executor, listener=listener)
        model_drift_loop = ModelDriftAndHealthLoop(ctx=context, model_validator=model_validator, training_pipeline=training_pipeline, self_improver=self_improver, listener=listener)
        register_runtime_loops(
            runner,
            market_scan_loop=market_scan_loop,
            model_drift_loop=model_drift_loop,
            hmm_training_loop=hmm_training_loop,
            sltp_monitoring_loop=sltp_monitoring_loop,
            listener=listener,
            orchestrator=orchestrator,
        )
        ws_url = secrets.get("WS_URL", "")
        polymarket_monitor = None
        onchain_monitor_enabled = _env_bool("POLYMARKET_ONCHAIN_MONITOR_ENABLED", False)
        if onchain_monitor_enabled and ws_url:
            target_wallet = secrets.get("TARGET_WALLET", "")
            polymarket_monitor = PolymarketMonitor(on_signal=orchestrator.on_signal, target_wallet=target_wallet or None, ws_url=ws_url, rpc_url=polygon_rpc)
        health_supervisor = build_health_supervisor(store, ledger, container.vault, orchestrator, secrets, polygon_rpc)
        health_sidecar = build_health_sidecar(store, ledger, orchestrator)
        user_ws_coro = build_user_stream(UserCLOBListener, ApiCreds, secrets, ledger, listener)
        redis_mode_listener = build_redis_mode_listener(
            ledger=ledger,
            orchestrator=orchestrator,
            broadcaster=broadcaster,
            lifecycle=self,
        )
        redis_task = asyncio.create_task(redis_mode_listener())
        dashboard_task = asyncio.create_task(_send_dashboard_when_ready()) if listener and _dashboard_target else None
        price_task = start_price_service(orchestrator)
        binance_task = start_binance_listener(store)

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
