from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from agents.health_monitor_agent import HealthMonitorAgent, HealthMonitorConfig
from core.health_supervisor_agent import HealthSupervisorAgent, HealthSupervisorConfig
from utils.config_loader import get_health_config
from utils.data_archiver import DataArchiver
from core.helpers import _env_bool
from utils.clob_feed_utils import extract_live_clob_token_ids

logger = logging.getLogger("LifecycleAssembly")


def build_dashboard_sender(listener: Any, chat_id: int | None, dashboard_msg: str):
    private_admin_ids = sorted(c for c in getattr(listener, "admin_chat_ids", set()) if c > 0) if listener else []
    dashboard_target = private_admin_ids[0] if private_admin_ids else (chat_id if chat_id and chat_id > 0 else None)
    if not listener or not dashboard_target:
        return dashboard_target, None

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    reply_markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton("📖 Manuel", callback_data="help_menu"), InlineKeyboardButton("📊 Statut", callback_data="help_page_3")]]
    )

    async def _send_dashboard_when_ready() -> None:
        if not await listener.wait_until_ready(timeout=45.0):
            return
        await listener.send_message(
            dashboard_msg,
            chat_id=dashboard_target,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )

    return dashboard_target, _send_dashboard_when_ready


def build_health_supervisor(store: Any, ledger: Any, vault: Any, orchestrator: Any, secrets: dict[str, str], polygon_rpc: str):
    wallet_manager_cls = __import__("polymarket.execution.wallet_manager", fromlist=["PolymarketWalletManager"]).PolymarketWalletManager
    return HealthSupervisorAgent(
        feature_store=store,
        ledger=ledger,
        wallet_manager=wallet_manager_cls(vault_handler=vault, polygon_rpc_url=polygon_rpc),
        data_archiver=DataArchiver(
            db_path=os.path.join(os.getenv("DATA_PATH", "data"), "feature_store.duckdb"),
            feature_store=store,
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
            disk_usage_critical_bytes=8_000_000_000,
        ),
    )


def build_health_sidecar(store: Any, ledger: Any, orchestrator: Any) -> HealthMonitorAgent:
    return HealthMonitorAgent(
        config=HealthMonitorConfig(
            heartbeat_interval_seconds=30.0,
            duckdb_prune_interval_seconds=86400.0,
            memory_check_interval_seconds=60.0,
            max_memory_rss_mb=float(get_health_config("memory_warning_mb", 1024, env_key="MAX_MEMORY_MB_THRESHOLD")),
            enable_ledger_reconciliation=_env_bool("HEALTH_SIDE_CAR_ENABLE_LEDGER_RECONCILIATION", True),
            enable_feature_store_maintenance=_env_bool("HEALTH_SIDE_CAR_ENABLE_FEATURE_STORE_MAINTENANCE", True),
        ),
        feature_store=store,
        ledger=ledger,
        broadcaster=orchestrator.broadcaster,
    )


def start_price_service(orchestrator: Any) -> asyncio.Task:
    from utils.exchange_price_service import ExchangePriceService

    price_service = ExchangePriceService()
    orchestrator.price_service = price_service
    return asyncio.create_task(price_service.start())


def attach_listener_runtime_components(
    listener: Any,
    *,
    ledger: Any,
    risk: Any,
    hmm: Any,
    store: Any,
    executor: Any,
    market_scanner: Any,
    copy_trading_agent: Any,
    wallet_manager: Any,
    secrets: dict[str, str],
    runner: Any = None,
) -> None:
    if not listener:
        return

    from utils.market_data_reader import MarketDataReader

    market_reader = MarketDataReader(polymarket_client=market_scanner.client)
    order_manager = None
    try:
        from utils.polymarket_order_manager import PolymarketOrderManager

        order_manager = PolymarketOrderManager(
            wallet_manager=wallet_manager,
            private_key=secrets.get("CLOB_PRIVATE_KEY"),
        )
    except Exception:
        pass

    listener.attach_components(
        ledger=ledger,
        risk=risk,
        hmm=hmm,
        store=store,
        executor=executor,
        scanner=market_scanner,
        copy_agent=copy_trading_agent,
        market_reader=market_reader,
        order_manager=order_manager,
        runner=runner,
    )
    try:
        from utils.pmxt_adapter_service import PMXTAdapterService

        listener._pmxt_service = PMXTAdapterService()
    except Exception as exc:
        logger.warning("PMXT adapter service unavailable: %s", exc)


def register_runtime_loops(
    runner: Any,
    *,
    market_scan_loop: Any,
    model_drift_loop: Any,
    hmm_training_loop: Any,
    sltp_monitoring_loop: Any,
    listener: Any,
    orchestrator: Any,
) -> None:
    runner.register_job("Model_Health_And_Drift", model_drift_loop.run, interval_sec=14400.0, resource_profile="heavy")
    runner.register_job("HMM_Training", hmm_training_loop.run, interval_sec=21600.0, resource_profile="heavy")
    runner.register_job("SLTP_Monitoring", sltp_monitoring_loop.run, interval_sec=10.0, resource_profile="latency")
    if listener and getattr(listener, "_pmxt_service", None):

        async def pmxt_monitored_job():
            try:
                result = await listener._pmxt_service.run_cycle()
                if result.get("status") == "FAILED":
                    reason = result.get("reason", "Unknown error")
                    logger.error("PMXT adapter failure: %s", reason)
                    if orchestrator and orchestrator.broadcaster:
                        await orchestrator.broadcaster.diffuser_message_au_canal(
                            "🚨 <b>PMXT ADAPTER FAILURE</b>\n"
                            "━━━━━━━━━━━━━━━━━━━━\n"
                            f"Reason: <code>{reason}</code>\n"
                            "<i>Archival chain may be broken. Check polars/pyarrow installation.</i>"
                        )
            except Exception as exc:
                logger.error("PMXT job error: %s", exc)

        runner.register_job(
            "PMXT_Auto_Cycle",
            pmxt_monitored_job,
            interval_sec=float(os.getenv("PMXT_ADAPTER_INTERVAL_SECONDS", "1800")),
            resource_profile="normal",
        )


def build_redis_mode_listener(
    *,
    ledger: Any,
    orchestrator: Any,
    broadcaster: Any,
    lifecycle: Any,
):
    async def redis_mode_listener():
        redis_url = (os.getenv("REDIS_URL", "") or "").strip()
        if not redis_url:
            logger.info("Redis hot-swap disabled: REDIS_URL not configured.")
            return
        try:
            import redis.asyncio as aioredis

            redis_client = aioredis.from_url(redis_url, decode_responses=True)
            pubsub = redis_client.pubsub()
            await pubsub.subscribe("lobstar:control:mode")
            logger.info("Listening for hot mode swaps on 'lobstar:control:mode'")

            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                data = json.loads(message["data"])
                if data.get("action") != "SWITCH_MODE":
                    continue
                new_mode = data.get("mode")
                current_mode = ledger.get_execution_mode() if ledger else "UNKNOWN"
                if not (new_mode and ledger and current_mode != new_mode):
                    continue
                ledger.set_execution_mode(new_mode)
                orchestrator.execution_mode = new_mode
                lifecycle.execution_mode = new_mode
                msg = (
                    "🔄 <b>[HOT SWAP]</b> Mode d'exécution changé via Redis: "
                    f"<code>{current_mode}</code> ➡️ <code>{new_mode}</code>"
                )
                logger.warning(msg)
                if broadcaster and broadcaster.notifier:
                    await broadcaster.notifier.send_async(msg, parse_mode="HTML")
        except ImportError:
            logger.warning("redis.asyncio not available. Redis hot-swap disabled.")
        except Exception as exc:
            logger.info("Redis hot-swap listener unavailable: %s", exc)

    return redis_mode_listener


def build_user_stream(user_listener_cls: Any, api_creds_cls: Any, secrets: dict[str, str], ledger: Any, listener: Any):
    if not (
        user_listener_cls
        and api_creds_cls
        and secrets.get("CLOB_API_KEY")
        and secrets.get("CLOB_API_SECRET")
        and secrets.get("CLOB_API_PASSPHRASE")
    ):
        return None
    try:
        user_creds = api_creds_cls(
            api_key=secrets["CLOB_API_KEY"],
            api_secret=secrets["CLOB_API_SECRET"],
            api_passphrase=secrets["CLOB_API_PASSPHRASE"],
        )
        user_listener = user_listener_cls(api_creds=user_creds)

        async def on_user_event(event: dict):
            event_type = event.get("event_type")
            if event_type == "order":
                if event.get("status") == "CLOSED":
                    logger.info("Order %s fully filled/closed.", event.get("order_id"))
                return
            if event_type != "trade":
                return
            order_id = event.get("order_id")
            size = float(event.get("size", 0.0))
            price = float(event.get("price", 0.0))
            if ledger:
                success = ledger.update_position_fill(
                    exchange_order_id=order_id,
                    filled_qty=size,
                    execution_price=price,
                )
                if success and listener:
                    await listener.send_message(
                        "⚡ <b>Live Fill Detected</b>\n"
                        f"Order: <code>{order_id[:8]}...</code>\n"
                        f"Size: <code>{size}</code> @ <code>{price}</code>",
                        parse_mode="HTML",
                    )

        user_listener.on_event = on_user_event
        return user_listener.run()
    except Exception as exc:
        logger.error("User CLOB listener initialization failed: %s", exc)
        return None


def start_binance_listener(store: Any) -> asyncio.Task:
    from utils.data_ingestion import BinanceWSListener

    binance_listener = BinanceWSListener(store=store, tickers=["BTCUSDT", "ETHUSDT", "SOLUSDT"])

    async def run_binance():
        try:
            await binance_listener._run()
        except Exception as exc:
            logger.error("Binance WS Listener failed: %s", exc)

    return asyncio.create_task(run_binance())


async def build_live_clob_feed(
    *,
    market_scanner: Any,
    ledger: Any,
    store: Any,
    snapshot_mgr: Any,
    orchestrator: Any,
    passive_executor: Any,
    listener: Any,
    clob_listener_cls: Any,
    run_blocking_fn: Any,
):
    if clob_listener_cls is None:
        return None, None

    try:
        top_markets = await run_blocking_fn(
            "prime live clob token ids",
            market_scanner.client.list_markets,
            limit=25,
            sort_by="volume",
            timeout=30.0,
        )
        live_token_ids = extract_live_clob_token_ids(top_markets)
        if ledger:
            try:
                open_positions = ledger.get_open_positions()
                for pos in open_positions:
                    token_id = pos.get("ticker")
                    if token_id and token_id not in live_token_ids:
                        live_token_ids.append(token_id)
            except Exception:
                pass
        if not live_token_ids:
            return None, None

        clob_listener = clob_listener_cls(token_ids=live_token_ids, store=store)

        async def _execute_exit(pos: dict) -> None:
            ticker = pos.get("ticker", "")
            pos_id = pos.get("position_id", "")
            entry = float(pos.get("entry_price", 0.0))
            exit_price = float(pos.get("exit_price", 0.0))
            entry_side = pos.get("side", "BUY").upper()
            exit_side = "SELL" if entry_side == "BUY" else "BUY"
            size = float(pos.get("size", 0.0))
            try:
                exec_res = await passive_executor.execute(
                    ticker=ticker,
                    side=exit_side,
                    price=exit_price,
                    size=size,
                    override_strict_maker=True,
                )
                if exec_res.get("status") in ("FILLED", "TAKER_FILLED"):
                    ledger.close_position(pos_id, exit_price=exit_price)
                    pnl_pct = ((exit_price - entry) / entry * 100) if entry > 0 else 0.0
                    if listener:
                        await listener.send_message(
                            "⏹ <b>[FAST-PATH] Position Closed</b>\n"
                            f"Ticker: <code>{ticker}</code>\n"
                            f"Exit: <code>{exit_price:.4f}</code>\n"
                            f"PnL: <b>{pnl_pct:+.2f}%</b>",
                            parse_mode="HTML",
                        )
            except Exception as exc:
                logger.error("Error in fast-path SL/TP execution: %s", exc)

        async def _persist_live_snapshot(snapshot: dict[str, Any]) -> None:
            snapshot_mgr.capture(
                category="SYSTEM",
                component="CLOB_ORDERBOOK",
                data=snapshot,
                tags=["live", "clob", snapshot.get("token_id", "unknown")],
            )
            swarm = getattr(orchestrator, "_swarm", None)
            if swarm is not None:
                await swarm.record_market_tick(snapshot)
            if not ledger:
                return
            ticker = snapshot.get("token_id")
            mid_price = snapshot.get("mid_price")
            if not (ticker and mid_price):
                return
            open_positions = [p for p in ledger.get_open_positions() if p.get("ticker") == ticker]
            if not open_positions:
                return
            due_positions = ledger.get_positions_due_for_exit({ticker: mid_price})
            for pos in due_positions:
                asyncio.create_task(_execute_exit(pos))

        return clob_listener, clob_listener.run(callback=_persist_live_snapshot)
    except Exception as exc:
        logger.warning("Live CLOB feed disabled: failed to prime token IDs (%s)", exc)
        return None, None
