import argparse
import asyncio
import contextlib
import fcntl
import getpass
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
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
from core.services.circuit_breaker import CircuitBreakerService
from utils.access_control import AccessControlManager
from utils.crypto_market_intelligence import CryptoMarketIntelligence, format_intelligence_report
from utils.data_archiver import DataArchiver
from utils.exceptions import QuantFatal
from utils.feature_store import FeatureStore
from utils.market_scanner import MarketScanner
from utils.model_validator import ModelValidator
from utils.clob_feed_utils import extract_live_clob_token_ids
from ai.agents.self_improvement_agent import SelfImprovementAgent
from utils.snapshot_manager import get_snapshot_manager
from scrapers.telegram_broadcaster import TelegramBroadcaster
from utils.notifier import TelegramNotifier
from utils.message_formatter import (
    format_scan_report,
    format_market_report,
    format_winning_bets_alert,
)
from scripts.daily_tca_report import DailyTcaReportConfig, DailyTcaReportJob
from utils.logging_setup import setup_logging
from utils.telegram_helpers import parse_chat_ids, parse_private_chat_ids
from core.swarm_supervisor import initialize_swarm_supervisor
from core.mlops_feedback_loop import LobstarMLOpsEngine
from core.quantum_runner import LobstarQuantumRunner
from utils.api_key_notifier import get_api_key_notifier
from telegram.constants import ParseMode

def should_broadcast_message(category: str, text: str) -> bool:
    import hashlib
    import json
    import os

    cleaned = "".join(text.split())
    msg_hash = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()

    filepath = "user_data/data/last_broadcast_hashes.json"
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    hashes = {}
    if os.path.exists(filepath):
        try:
            with open(filepath, "r") as f:
                hashes = json.load(f)
        except Exception:
            pass

    if hashes.get(category) == msg_hash:
        return False

    hashes[category] = msg_hash
    try:
        with open(filepath, "w") as f:
            json.dump(hashes, f)
    except Exception:
        pass
    return True
from core.orchestrator import LobstarOrchestrator
from core.health_monitor import LobstarHealthMonitor
from core.health_supervisor_agent import HealthSupervisorAgent, HealthSupervisorConfig
from agents.health_monitor_agent import HealthMonitorAgent, HealthMonitorConfig
from scrapers.clob_listener import CLOBListener
from scrapers.user_clob_listener import UserCLOBListener
from py_clob_client import ApiCreds

logger = setup_logging()

DEFAULT_TICKERS = ["SOL", "BTC", "ETH"]
PROD_CONFIRMATION_TEXT = "I UNDERSTAND REAL CAPITAL IS AT RISK"
PROD_SECOND_FACTOR_ENV = "LOBSTAR_PROD_CONFIRM_SECRET"


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


def require_production_confirmation(execution_mode: str) -> None:
    """Require an interactive confirmation and a second factor before PROD starts."""
    if execution_mode.upper() != "PROD":
        return

    expected_secret = os.getenv(PROD_SECOND_FACTOR_ENV, "").strip()
    if not expected_secret:
        raise QuantFatal(f"{PROD_SECOND_FACTOR_ENV} is required before PROD mode can start.")

    if not sys.stdin.isatty():
        raise QuantFatal("PROD mode requires an interactive terminal confirmation.")

    typed_confirmation = input(
        f"Type '{PROD_CONFIRMATION_TEXT}' to start PROD mode: "
    ).strip()
    if typed_confirmation != PROD_CONFIRMATION_TEXT:
        raise QuantFatal("PROD mode confirmation text did not match.")

    typed_secret = getpass.getpass("Enter PROD second-factor secret: ").strip()
    if typed_secret != expected_secret:
        raise QuantFatal("PROD second-factor secret did not match.")


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
    tenant_wallet = _derive_public_wallet(private_key_raw)
    if chat_id and tenant_wallet:
        access_control.assigner_wallet_a_chat(chat_id, tenant_wallet)
    return access_control, chat_id


def build_copy_trading_agent(risk_engine: Any = None) -> CopyTradingAgent | None:
    copy_wallet = os.getenv("COPY_WALLET", "").strip()
    if not copy_wallet:
        return None
    copy_config = CopyConfig(
        target_wallet=copy_wallet,
        copy_multiplier=float(os.getenv("COPY_MULTIPLIER", "0.1")),
        max_copy_notional=float(os.getenv("COPY_MAX_NOTIONAL", "100.0")),
        buy_only=os.getenv("COPY_BUY_ONLY", "true").lower() == "true",
    )
    return CopyTradingAgent(copy_config, risk_engine=risk_engine)


def build_telegram_listener(
    secrets: dict,
    on_signal: Callable[[dict], None],
    chat_id: int | None,
    access_control: AccessControlManager,
) -> TelegramListener:
    token = secrets.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise QuantFatal("TELEGRAM_BOT_TOKEN is missing from Vault/Environment.")
    raw_private = secrets.get("TELEGRAM_PRIVATE_CHAT_IDS") or os.getenv("TELEGRAM_PRIVATE_CHAT_IDS", "")
    if not raw_private and chat_id:
        raw_private = str(chat_id)
    private_chat_ids = parse_private_chat_ids(raw_private)
    raw_admin = secrets.get("TELEGRAM_ADMIN_CHAT_IDS") or os.getenv("TELEGRAM_ADMIN_CHAT_IDS", "")
    admin_chat_ids = parse_chat_ids(raw_admin) or set()
    allow_private_messages = True
    return TelegramListener(
        bot_token=token,
        on_signal=on_signal,
        chat_id=chat_id,
        access_control=access_control,
        private_chat_ids=private_chat_ids,
        admin_chat_ids=admin_chat_ids,
        allow_private_messages=allow_private_messages,
    )


def build_broadcaster(
    container: ServiceContainer, pipeline: TrainingPipeline, scanner: MarketScanner
) -> TelegramBroadcaster:
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
        feature_store=container.store,
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
    """
    Execute a blocking function in a thread pool with timeout and contextual error logging.

    Args:
        label: Human-readable label for logging (e.g., "market scan", "vault lookup")
        func: The blocking function to execute
        *args: Positional arguments for func
        timeout: Timeout in seconds
        **kwargs: Keyword arguments for func

    Returns:
        Result from func

    Raises:
        TimeoutError: If execution exceeds timeout
    """
    try:
        logger.debug(f"🔄 [BLOCKING] Starting: {label} (timeout={timeout}s, args={len(args)}, kwargs={list(kwargs.keys())})")
        result = await asyncio.wait_for(asyncio.to_thread(func, *args, **kwargs), timeout=timeout)
        logger.debug(f"✅ [BLOCKING] Completed: {label}")
        return result
    except asyncio.TimeoutError:
        logger.error(
            f"❌ [TIMEOUT] {label} exceeded {timeout}s limit\n"
            f"   Function: {func.__name__}\n"
            f"   Args: {args}\n"
            f"   Kwargs: {list(kwargs.keys())}"
        )
        logger.error(f"🚨 [CRITICAL] System resource bottleneck detected in {label}")
        raise TimeoutError(f"{label} timed out after {timeout}s") from None
    except Exception as e:
        logger.error(
            f"❌ [ERROR] {label} failed with exception:\n"
            f"   Function: {func.__name__}\n"
            f"   Exception: {type(e).__name__}: {e}\n"
            f"   Args: {args}\n"
            f"   Kwargs: {list(kwargs.keys())}"
        )
        raise


def _fetch_rpc_blocking(rpc_url: str) -> dict[str, Any]:
    import json
    import urllib.request

    req = urllib.request.Request(
        rpc_url,
        data=b'{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}',
        headers={
            "Content-Type": "application/json",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
                " AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        },
    )
    with urllib.request.urlopen(req, timeout=5) as response:  # nosec B310
        return json.loads(response.read().decode())


async def _check_rpc_dry_run(rpc_url: str) -> dict[str, Any]:
    return await asyncio.to_thread(_fetch_rpc_blocking, rpc_url)


def _setup_ml_features(training_pipeline: TrainingPipeline) -> None:
    """Registers features for autonomous retraining loop."""
    DEFAULT_FEATURES = ["oi_5min", "tam_state", "spread_bps", "mid_price"]
    for tkr in DEFAULT_TICKERS:
        training_pipeline.register_features(tkr, DEFAULT_FEATURES, target_feature="mid_price")


def _setup_quantum_runner(
    runner: LobstarQuantumRunner,
    container: ServiceContainer,
    freqai: Any,
    cognitive_brain: LobstarCognitiveBrain,
    mlops_engine: LobstarMLOpsEngine,
    autonomic_healer: "LobstarAutonomicHealer",
    broadcaster: Any,
) -> None:
    """Schedules cron/quantum runner background jobs using English hook register_job."""
    runner.register_job("Web_Scraper_Ticks", freqai.stream_ticks_to_duckdb, interval_sec=0.1)
    if cognitive_brain.arbitrage_engine:
        runner.register_job("Arbitrage_Matrix_Scan", cognitive_brain.arbitrage_engine.scanner_anomalies, interval_sec=5.0)
    runner.register_job("MLOps_Health_Check", mlops_engine.analyser_sante_brain, interval_sec=14400.0)

    async def prune_feature_store():
        store = getattr(cognitive_brain, "store", None) or getattr(container, "store", None)
        if store and mlops_engine.should_prune(interval_hours=24):
            mlops_engine.prune_feature_store(store, raw_retention_days=7, vacuum=True)

    # Ensure log directory exists
    os.makedirs(os.path.dirname(autonomic_healer.log_path), exist_ok=True)

    async def run_healer():
        erreurs = autonomic_healer.analyser_nouveaux_logs()
        for err in erreurs:
            await autonomic_healer.deployer_correctif_autonome(err)

    runner.register_job("Autonomic_Healer", run_healer, interval_sec=2.0)
    runner.register_job("FeatureStore_Prune", prune_feature_store, interval_sec=3600.0)

    # ─── 1. System Connectivity & Credentials Check ───
    async def system_connectivity_check():
        import httpx
        from utils.api_key_check import get_api_key_notifier
        # Check all critical keys
        api_check = get_api_key_notifier().check_all_keys(runtime_secrets=container.secrets)
        if api_check["missing"]:
            alert = get_api_key_notifier().format_telegram_alert(api_check)
            logger.warning(f"⚠️ [CREDENTIALS] Missing API keys: {api_check['missing']}")
            if broadcaster and broadcaster.notifier:
                await broadcaster.notifier.send_async(alert, parse_mode="Markdown")

        # Check Polygon RPC and Polymarket Gamma API connectivity
        timeout = httpx.Timeout(5.0, connect=3.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            rpc_url = container.secrets.get("POLYGON_RPC_URL") or os.getenv("POLYGON_RPC_URL")
            if rpc_url:
                try:
                    res = await _check_rpc_dry_run(rpc_url)
                    if "result" not in res:
                        logger.warning("⚠️ [CONNECTIVITY] Alchemy RPC returned invalid response")
                except Exception as e:
                    logger.warning(f"⚠️ [CONNECTIVITY] Alchemy RPC offline: {e}")

            try:
                r = await client.get("https://gamma-api.polymarket.com/tags?limit=1", timeout=3.0)
                if r.status_code >= 500:
                    logger.warning(f"⚠️ [CONNECTIVITY] Polymarket Gamma API returned status {r.status_code}")
            except Exception as e:
                logger.warning(f"⚠️ [CONNECTIVITY] Polymarket Gamma API offline: {e}")

    runner.register_job("System_Connectivity_Check", system_connectivity_check, interval_sec=1800.0)

    # ─── 2. Database WAL & Storage Optimization ───
    async def db_storage_optimization():
        ledger = getattr(container, "ledger", None)
        if not ledger:
            return
        try:
            # Clean SQLite WAL files, run VACUUM cleanly, prune indexes
            cursor = ledger.conn.cursor()
            cursor.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            cursor.execute("PRAGMA optimize")
            logger.info("💾 [AUTO MAINTENANCE] SQLite Database WAL truncated and storage optimized successfully.")
        except Exception as e:
            logger.error(f"❌ [AUTO MAINTENANCE] Database optimization failed: {e}")

    runner.register_job("DB_Storage_Optimization", db_storage_optimization, interval_sec=7200.0)

    # ─── 3. Dynamic ML Reinforcement & Calibration Loop ───
    async def dynamic_ml_reinforcement():
        pipeline = getattr(container, "training_pipeline", None)
        ledger = getattr(container, "ledger", None)
        if not pipeline or not ledger:
            return
        try:
            from scripts.rl_feedback_loop import run_rl_feedback_loop
            # Adjust EWMA learning weights from paper trading outcomes
            await run_blocking(
                "RL feedback loop",
                run_rl_feedback_loop,
                timeout=120.0,
            )
            # Retrain probability calibrators
            tickers = os.getenv("MODEL_TICKERS", "SOL,BTC,ETH").split(",")
            tickers = [t.strip().upper() for t in tickers if t.strip()]
            for ticker in tickers:
                calibration_log = pipeline.update_calibration_from_paper_trades(ticker, ledger)
                if calibration_log:
                    logger.info(f"🎯 [AUTO CALIBRATION] Updated Isotonic Calibrator weights for {ticker}: {calibration_log}")
        except Exception as e:
            logger.error(f"❌ [AUTO CALIBRATION] Dynamic ML calibration failed: {e}")

    runner.register_job("Dynamic_ML_Reinforcement", dynamic_ml_reinforcement, interval_sec=3600.0)

    async def daily_tca_report():
        metrics_log_path = os.getenv(
            "EXECUTION_METRICS_LOG_PATH",
            os.path.join(os.getenv("DATA_PATH", "user_data/data"), "execution_metrics.jsonl"),
        )
        state_path = os.getenv(
            "DAILY_TCA_REPORT_STATE_PATH",
            os.path.join(os.getenv("DATA_PATH", "user_data/data"), "daily_tca_report_state.json"),
        )
        job = DailyTcaReportJob(
            broadcaster=broadcaster,
            config=DailyTcaReportConfig(
                metrics_log_path=metrics_log_path,
                state_path=state_path,
                send_hour_utc=int(os.getenv("DAILY_TCA_REPORT_HOUR_UTC", "8")),
                send_minute_utc=int(os.getenv("DAILY_TCA_REPORT_MINUTE_UTC", "0")),
                send_window_minutes=int(os.getenv("DAILY_TCA_REPORT_WINDOW_MINUTES", "5")),
            ),
        )
        await job.run()

    runner.register_job("Daily_TCA_Report", daily_tca_report, interval_sec=60.0)

    async def train_and_rotate_models():
        pipeline = getattr(container, "training_pipeline", None)
        if not pipeline:
            return
        tickers = os.getenv("MODEL_TICKERS", "SOL,BTC,ETH").split(",")
        tickers = [t.strip().upper() for t in tickers if t.strip()]
        feature_names = [name.strip() for name in os.getenv(
            "MODEL_FEATURES",
            "oi_5min,tam_state,spread_bps,mid_price,binance_return_1m,binance_order_imbalance,polymarket_spread_premium",
        ).split(",") if name.strip()]
        target_feature = os.getenv("MODEL_TARGET_FEATURE", "mid_price")
        for ticker in tickers:
            pipeline.register_features(ticker, feature_names, target_feature=target_feature)
            result = pipeline.train(ticker)
            if result:
                pipeline.prune_model_artifacts(ticker=ticker, keep_latest=2)

    runner.register_job("Model_Retrain_Rotate", train_and_rotate_models, interval_sec=14400.0)


async def _dry_run_report(mode: str, circuit_breaker: CircuitBreakerService, store: FeatureStore, container: ServiceContainer) -> None:
    """Logs dry-run validation report with real system state checks."""
    logger.info("=== DRY RUN MODE ===")
    component_status: dict[str, bool] = {}

    def _mark(component: str, ok: bool) -> None:
        component_status[component] = ok

    def _is_available(value: Any) -> bool:
        return value is not None

    # 1. Validate vault and RAM dictionary state of active session wallets
    try:
        vault_secrets = container.secrets or {}
        vault_count = len(vault_secrets)
        required_secrets = ["TELEGRAM_BOT_TOKEN", "CLOB_PRIVATE_KEY"]
        missing_secrets = [s for s in required_secrets if not vault_secrets.get(s)]
        vault_status = "OK" if vault_count > 0 and not missing_secrets else "MISSING"
        _mark("vault", vault_status != "MISSING")

        session_wallet_count = container.vault.compter_wallets_session()
        logger.info(f"Vault RAM session wallets state: {session_wallet_count} active session wallets in memory.")
        logger.info(f"Vault Secrets: {vault_status} ({vault_count} secrets loaded, {len(missing_secrets)} missing)")
    except Exception as e:
        logger.info(f"Vault Check: ERROR ({e})")

    # 2. Verify Alchemy RPC connectivity
    rpc_url = container.secrets.get("POLYGON_RPC_URL") or os.getenv("POLYGON_RPC_URL")
    if rpc_url:
        try:
            res = await _check_rpc_dry_run(rpc_url)
            if "result" in res:
                block = int(res["result"], 16)
                logger.info(f"Alchemy RPC Connectivity: OK (Current Block: {block})")
            else:
                logger.warning("Alchemy RPC Connectivity: FAILED (Invalid JSON-RPC response)")
        except Exception as e:
            logger.warning(f"Alchemy RPC Connectivity: FAILED ({e})")
    else:
        logger.warning("Alchemy RPC Connectivity: SKIPPED (No POLYGON_RPC_URL configured)")

    # Validate CLOB engine with actual connectivity
    try:
        freqai_status = "OK" if container.freqai else "MISSING"
        if container.freqai:
            # Dry-run should confirm object wiring, not require live exchange liquidity.
            try:
                mid = await container.freqai.get_midpoint("SOL")
                if mid and mid > 0:
                    logger.info(f"CLOB Engine: OK (SOL Midpoint: {mid})")
                    freqai_status = "OK"
                else:
                    logger.warning("CLOB Engine: DEGRADED (No live midpoint yet; engine wired correctly)")
                    freqai_status = "DEGRADED"
            except Exception as e:
                logger.warning(f"CLOB Engine: DEGRADED ({e})")
                freqai_status = "DEGRADED"
    except Exception as e:
        logger.info(f"CLOB Engine: ERROR ({e})")
        freqai_status = "FAILED"
    _mark("freqai", freqai_status in {"OK", "DEGRADED"})

    # Validate ledger with actual database check
    try:
        ledger_status = "OK" if container.ledger else "MISSING"
        if container.ledger:
            try:
                # Using summary is safer than get_available_capital
                summary = container.ledger.get_capital_summary()
                balance = summary.get("available_capital", 0.0)
                positions = container.ledger.get_open_positions()
                logger.info(f"Ledger: OK (Balance: ${balance:.2f}, Positions: {len(positions)})")
                ledger_status = "OK"
            except Exception as e:
                logger.warning(f"Ledger: DEGRADED ({e})")
                ledger_status = "DEGRADED"
    except Exception as e:
        logger.info(f"Ledger: ERROR ({e})")
        ledger_status = "FAILED"
    _mark("ledger", ledger_status in {"OK", "DEGRADED"})

    # Validate HMM with actual model check
    try:
        hmm_status = "OK" if container.hmm else "MISSING"
        if container.hmm:
            try:
                # Test regime prediction labels (now added back)
                regimes = container.hmm.get_regime_labels()
                if regimes:
                    logger.info(f"HMMRegimeFilter: OK ({len(regimes)} regimes available)")
                    hmm_status = "OK"
                else:
                    logger.warning("HMMRegimeFilter: DEGRADED (No regime labels yet; filter object loaded)")
                    hmm_status = "DEGRADED"
            except Exception as e:
                logger.warning(f"HMMRegimeFilter: DEGRADED ({e})")
                hmm_status = "DEGRADED"
    except Exception as e:
        logger.info(f"HMMRegimeFilter: ERROR ({e})")
        hmm_status = "FAILED"
    _mark("hmm", hmm_status in {"OK", "DEGRADED"})

    # Validate risk engine with actual calculation
    try:
        risk_status = "OK" if container.risk else "MISSING"
        if container.risk:
            try:
                # Test risk calculation (now added back)
                max_size = container.risk.calculate_max_position_size("SOL", 100.0)
                concentration = container.risk.get_concentration("SOL")
                logger.info(
                    f"PortfolioRiskEngine: OK (Max size: ${max_size:.2f}, Concentration: {concentration:.1%})"
                )
                risk_status = "OK"
            except Exception as e:
                logger.warning(f"PortfolioRiskEngine: DEGRADED ({e})")
                risk_status = "DEGRADED"
    except Exception as e:
        logger.info(f"PortfolioRiskEngine: ERROR ({e})")
        risk_status = "FAILED"
    _mark("risk", risk_status in {"OK", "DEGRADED"})

    # Validate executor with actual status
    try:
        executor_status = "OK" if container.executor else "MISSING"
        if container.executor:
            try:
                # Test executor status
                timeout = getattr(container.executor, 'timeout', 30)
                queue_size = getattr(container.executor, 'queue_size', 0)
                logger.info(f"PassiveExecutor: OK (Timeout: {timeout}s, Queue: {queue_size})")
            except Exception as e:
                logger.info(f"PassiveExecutor: STATUS_ERROR ({e})")
                executor_status = "STATUS_ERROR"
    except Exception as e:
        logger.info(f"PassiveExecutor: ERROR ({e})")

    # Circuit breaker with actual status
    try:
        cb_status = circuit_breaker.status_report
        cb_allowed = circuit_breaker.is_allowed()
        logger.info(f"CircuitBreaker: {cb_status} (Allowed: {cb_allowed})")
    except Exception as e:
        logger.info(f"CircuitBreaker: ERROR ({e})")

    # Feature store with actual stats
    try:
        store_stats = store.get_stats() if store else "N/A"
        logger.info(f"FeatureStore: OK ({store_stats})")
    except Exception as e:
        logger.info(f"FeatureStore: PARTIAL ({e})")

    logger.info(f"Execution Mode: {mode}")
    logger.info("Telegram Bot: SKIPPED (dry-run)")

    # Overall status with real validation
    component_status["executor"] = executor_status == "OK"

    all_ok = all(component_status.values())

    if all_ok:
        logger.info("✅ Pipeline validated successfully. All core components operational.")
    else:
        failed_components = [k for k, v in component_status.items() if not v]
        logger.warning(f"⚠️ Pipeline has {len(failed_components)} failed components: {', '.join(failed_components)}")

    logger.info(f"Active mode: {mode} — {'Virtual' if mode in ('REPLAY', 'PAPER') else 'Real capital at risk.'}")


async def _run_services_loop(
    listener: TelegramListener,
    clob_feed_coro: Any,
    user_ws_coro: Any,
    polymarket_monitor: Any,
    health_supervisor: Any,
    health_sidecar: Any,
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
    clob_feed_task = None
    user_ws_task = None
    monitor_task = None
    telegram_task = None
    runner_task = None
    health_supervisor_task = None
    health_sidecar_task = None
    try:
        # Start core components
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
        await asyncio.gather(*tasks)
    finally:
        logger.info("💤 [CLEANUP] Initiating graceful shutdown...")

        # Stop core services first
        runner.stop()
        logger.debug("✅ QuantumRunner stopped")

        await orchestrator.stop()
        logger.debug("✅ Orchestrator stopped")

        await health_monitor.stop()
        logger.debug("✅ HealthMonitor stopped")

        if polymarket_monitor:
            try:
                await polymarket_monitor.stop()
                logger.debug("✅ PolymarketMonitor stopped")
            except Exception as e:
                logger.warning(f"Error stopping polymarket_monitor: {e}")
        if health_supervisor:
            try:
                health_supervisor.stop()
                logger.debug("✅ HealthSupervisor stopped")
            except Exception as e:
                logger.warning(f"Error stopping health_supervisor: {e}")
        if health_sidecar:
            try:
                health_sidecar.stop()
                logger.debug("✅ HealthMonitorSidecar stopped")
            except Exception as e:
                logger.warning(f"Error stopping health_sidecar: {e}")

        # Properly cancel all tasks with exception handling
        tasks_to_cancel = []
        if telegram_task and not telegram_task.done():
            telegram_task.cancel()
            tasks_to_cancel.append(telegram_task)
        if scan_task and not scan_task.done():
            scan_task.cancel()
            tasks_to_cancel.append(scan_task)
        if retrain_task and not retrain_task.done():
            retrain_task.cancel()
            tasks_to_cancel.append(retrain_task)
        if clob_feed_task and not clob_feed_task.done():
            clob_feed_task.cancel()
            tasks_to_cancel.append(clob_feed_task)
        if user_ws_task and not user_ws_task.done():
            user_ws_task.cancel()
            tasks_to_cancel.append(user_ws_task)
        if monitor_task and not monitor_task.done():
            monitor_task.cancel()
            tasks_to_cancel.append(monitor_task)
        if health_supervisor_task and not health_supervisor_task.done():
            health_supervisor_task.cancel()
            tasks_to_cancel.append(health_supervisor_task)
        if health_sidecar_task and not health_sidecar_task.done():
            health_sidecar_task.cancel()
            tasks_to_cancel.append(health_sidecar_task)
        if runner_task and not runner_task.done():
            runner_task.cancel()
            tasks_to_cancel.append(runner_task)

        # Wait for all cancellations to complete
        if tasks_to_cancel:
            logger.debug(f"Awaiting cancellation of {len(tasks_to_cancel)} tasks...")
            await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
            logger.debug("✅ All tasks cancelled")

        logger.info("✅ [CLEANUP] Graceful shutdown complete")


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

    circuit_breaker = CircuitBreakerService({"name": "CLOB_Execution"})

    copy_trading_agent = build_copy_trading_agent(risk_engine=risk)

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

    # Set execution mode early to prevent race conditions
    if execution_mode:
        ledger.set_execution_mode(execution_mode)
    mode = ledger.get_execution_mode()

    # REAL CAPITAL SYNC (User Request)
    if mode == "PROD":
        logger.info("📡 [SYNC] Sincronisation du capital réel avec la blockchain...")
        await container.sync_real_capital()

    if dry_run:
        await _dry_run_report(mode, circuit_breaker, store, container)
        return

    market_scanner = MarketScanner()
    crypto_intelligence = build_crypto_intelligence()
    cognitive_brain = build_cognitive_brain(store, market_scanner, training_pipeline)
    broadcaster = build_broadcaster(container, training_pipeline, market_scanner)
    live_clob_feed_coro = None

    # Initialize autonomic healer
    from core.autonomic_healer import LobstarAutonomicHealer
    autonomic_healer = LobstarAutonomicHealer(
        log_file_path="logs/pm2-out.log",
    )

    mlops_engine = LobstarMLOpsEngine()
    runner = LobstarQuantumRunner()
    _setup_quantum_runner(runner, container, freqai, cognitive_brain, mlops_engine, autonomic_healer, broadcaster)

    # Build listener FIRST before orchestrator and swarm (prevents race conditions)
    listener = build_telegram_listener(
        secrets=secrets,
        on_signal=None,  # Will set after orchestrator creation
        chat_id=chat_id,
        access_control=access_control,
    )

    logger.info("✅ Telegram listener initialized (ready for callbacks)")

    # Instantiate the orchestrator with listener passed directly
    orchestrator = LobstarOrchestrator(
        container=container,
        secrets=secrets,
        execution_mode=execution_mode,
        listener=listener,  # Pass listener directly (dependency injection)
        circuit_breaker=circuit_breaker,
        snapshot_mgr=snapshot_mgr,
        cognitive_brain=cognitive_brain,
        copy_trading_agent=copy_trading_agent,
        market_scanner=market_scanner,
        lobstar_agent=lobstar,
        access_control=access_control,
    )

    # Attach the orchestrator's broadcaster to autonomic healer for notifications
    autonomic_healer.broadcaster = orchestrator.broadcaster

    # NOW attach the orchestrator's signal handler to listener (callback chain)
    listener.on_signal = orchestrator.on_signal

    # THEN initialize swarm with callbacks (listener is now guaranteed to exist)
    swarm_supervisor = await initialize_swarm_supervisor(mode=execution_mode)
    data_diag = swarm_supervisor.check_data_gaps()
    logger.info(f"📊 Data Gap Check: {data_diag}")

    async def on_mode_change(new_mode):
        mode_str = new_mode.value
        logger.warning(f"⚠️ Swarm triggered mode change: {mode_str}")
        ledger.set_execution_mode(mode_str)
        # listener is guaranteed to exist at this point
        await listener.send_message(f"🔄 *Mode changed to:* `{mode_str}` (Swarm Supervisor)")

    async def on_circuit_breaker(reason, data):
        logger.critical(f"🚨 Swarm Circuit Breaker: {reason.value}")
        # listener is guaranteed to exist at this point
        await listener.send_message(
            f"🚨 *CIRCUIT BREAKER*\nReason: `{reason.value}`\nData: `{data}`"
        )

    swarm_supervisor.set_mode_change_callback(on_mode_change)
    swarm_supervisor.set_circuit_breaker_callback(on_circuit_breaker)
    logger.info("✅ Swarm supervisor callbacks registered (listener guaranteed to exist)")

    health_monitor = LobstarHealthMonitor(
        orchestrator=orchestrator,
        runner=runner,
        port=8080,
    )

    api_check = get_api_key_notifier().check_all_keys(runtime_secrets=secrets)

    # Get System Metrics for the Dashboard
    try:
        import psutil
        cpu_usage = psutil.cpu_percent()
        ram_usage = psutil.virtual_memory().percent
    except ImportError:
        logger.warning("psutil not installed; using placeholder metrics")
        cpu_usage = 0.0
        ram_usage = 0.0

    # Build a "Perfect & Intuitive" Startup Dashboard
    alert = get_api_key_notifier().format_telegram_alert(api_check)
    dashboard_msg = (
        f"🦞 *LOBSTAR COMMAND CENTER — ONLINE*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🚀 *Status*: `RUNNING`\n"
        f"📡 *Mode*: `{execution_mode}`\n"
        f"💻 *System*: CPU `{cpu_usage}%` | RAM `{ram_usage}%` \n\n"
        f"{alert}\n\n"
        f"🔗 _Tapez /help pour explorer les fonctions._"
    )

    try:
        if chat_id:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            reply_markup = InlineKeyboardMarkup([[
                InlineKeyboardButton("📖 Manuel", callback_data="help_menu"),
                InlineKeyboardButton("📊 Statut", callback_data="help_page_3")
            ]])
            sent = await listener.send_message(
                dashboard_msg,
                chat_id=chat_id,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup,
            )
            if sent:
                logger.info("📡 [STARTUP] Intuitive Command Center dashboard sent.")
            else:
                logger.warning("📡 [STARTUP] Intuitive Command Center dashboard deferred: Telegram bot not ready.")
    except Exception as e:
        logger.error(f"❌ Failed to send Startup Dashboard: {e}")

    from utils.market_data_reader import MarketDataReader
    market_reader = MarketDataReader(polymarket_client=market_scanner.client)

    order_manager: Any = None
    try:
        from utils.polymarket_order_manager import PolymarketOrderManager
        from core.wallet_manager import PolymarketWalletManager
        wallet_mgr = PolymarketWalletManager(
            vault_handler=container.vault,
            polygon_rpc_url=secrets.get("POLYGON_RPC_URL", ""),
        )
        order_manager = PolymarketOrderManager(
            wallet_manager=wallet_mgr,
            private_key=secrets.get("CLOB_PRIVATE_KEY"),
        )
        logger.info("✅ PolymarketOrderManager initialized")
    except Exception as e:
        logger.warning(f"PolymarketOrderManager init skipped: {e}")

    listener.attach_components(
        ledger=ledger,
        risk=risk,
        hmm=hmm,
        store=store,
        executor=passive_executor,
        scanner=market_scanner,
        copy_agent=copy_trading_agent,
        market_reader=market_reader,
        order_manager=order_manager,
    )

    clob_listener = None
    live_clob_feed_coro = None
    try:
        top_markets = await run_blocking(
            "prime live clob token ids",
            market_scanner.client.list_markets,
            limit=25,
            sort_by="volume",
            timeout=30.0,
        )
        live_token_ids = extract_live_clob_token_ids(top_markets)

        # Add tickers from currently open positions to ensure SL/TP monitoring is live
        if ledger:
            try:
                open_pos = ledger.get_open_positions()
                for pos in open_pos:
                    tid = pos.get("ticker")
                    if tid and tid not in live_token_ids:
                        live_token_ids.append(tid)
                        logger.info(f"Adding open position ticker {tid} to live monitoring.")
            except Exception as e:
                logger.warning(f"Failed to fetch open positions for priming: {e}")

        if live_token_ids:
            clob_listener = CLOBListener(token_ids=live_token_ids, store=store)

            async def _persist_live_snapshot(snapshot: dict[str, Any]) -> None:
                snapshot_mgr.capture(
                    category="SYSTEM",
                    component="CLOB_ORDERBOOK",
                    data=snapshot,
                    tags=["live", "clob", snapshot.get("token_id", "unknown")],
                )

                # Fast Path: Check SL/TP directly from live snapshots
                if ledger:
                    ticker = snapshot.get("token_id")
                    mid_price = snapshot.get("mid_price")
                    if ticker and mid_price:
                        # Find open positions for this ticker
                        open_pos = [p for p in ledger.get_open_positions() if p.get("ticker") == ticker]
                        if open_pos:
                            due = ledger.get_positions_due_for_exit({ticker: mid_price})
                            for pos in due:
                                logger.info(f"⚡ [FAST-PATH SL/TP] Triggered for {ticker} @ {mid_price}")
                                # Execute exit immediately
                                asyncio.create_task(_execute_exit(pos))

            async def _execute_exit(pos: dict):
                """Helper to execute an exit order in the background."""
                reason = pos.get("exit_reason", "unknown")
                ticker = pos.get("ticker", "")
                pos_id = pos.get("position_id", "")
                entry = float(pos.get("entry_price", 0.0))
                exit_p = float(pos.get("exit_price", 0.0))

                entry_side = pos.get("side", "BUY").upper()
                exit_side = "SELL" if entry_side == "BUY" else "BUY"
                size = float(pos.get("size", 0.0))

                try:
                    exec_res = await passive_executor.execute(
                        ticker=ticker,
                        side=exit_side,
                        price=exit_p,
                        size=size,
                        override_strict_maker=True,
                    )
                    if exec_res.get("status") in ("FILLED", "TAKER_FILLED"):
                        ledger.close_position(pos_id, exit_price=exit_p)
                        pnl_pct = ((exit_p - entry) / entry * 100) if entry > 0 else 0.0
                        msg = (
                            f"⏹ *[FAST-PATH] Position Closed: {reason}*\n"
                            f"Ticker: `{ticker}`\nExit: `${exit_p:.4f}`\nPnL: `{pnl_pct:+.2f}%`"
                        )
                        await listener.send_message(msg, parse_mode="Markdown")
                    else:
                        logger.error(f"Fast-path SL/TP failed for {ticker}: {exec_res}")
                except Exception as e:
                    logger.error(f"Error in fast-path SL/TP execution: {e}")

            live_clob_feed_coro = clob_listener.run(callback=_persist_live_snapshot)
            logger.info(
                "✅ Live CLOB feed armed with %s token IDs from top markets",
                len(live_token_ids),
            )
        else:
            logger.warning("Live CLOB feed disabled: no token IDs resolved from top markets")
    except Exception as e:
        logger.warning(f"Live CLOB feed disabled: failed to prime token IDs ({e})")

    async def model_drift_and_health_check():
        """Periodic model health, drift check, and self-improvement analysis."""
        for ticker in DEFAULT_TICKERS:
            try:
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
                        logger.exception("Retraining failed for %s", ticker)
                        await listener.send_message(
                            f"❌ *RECALIBRATION FAILED: {ticker}*\n\nError: {e}",
                            parse_mode="Markdown",
                        )

                    self_improver.log_incident("MODEL_DRIFT", f"Drift detected for {ticker}", "Distribution shift", "Prediction accuracy degradation")
            except Exception as e:
                logger.error(f"Failed drift check/retrain for {ticker}: {e}")

        try:
            imp_report = await run_blocking(
                "self-improvement report",
                self_improver.generate_improvement_report,
                timeout=30.0,
            )
            await listener.send_message(imp_report, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Failed self-improvement report: {e}")

    # Register the model health & self-improvement job on the runner
    runner.register_job("Model_Health_And_Drift", model_drift_and_health_check, interval_sec=14400.0)

    async def _health_check_loop():
        """Periodic model health, drift check, and self-improvement analysis (standby)."""
        pass # Runner handles scheduling via model_drift_and_health_check

    async def _market_scan_loop() -> None:
        from utils.market_scanner import SCAN_INTERVAL_SECONDS

        # Wait for listener to be fully initialized
        for _ in range(30):
            if listener.application:
                break
            await asyncio.sleep(1)

        logger.info(f"Market scanner started (interval={SCAN_INTERVAL_SECONDS}s)")

        # Timing trackers
        last_crypto_intelligence_at = 0.0
        crypto_intelligence_interval = int(os.getenv("CRYPTO_INTELLIGENCE_INTERVAL_SECONDS", "1800"))
        last_sentiment = None
        iteration_count = 0
        first_scan_completed = False

        while True:
            try:
                iteration_count += 1
                is_first_scan = iteration_count == 1

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

                    # ─── FIRST SCAN INITIALIZATION (Only on iteration 1) ───
                    if is_first_scan:
                        logger.info("🎯 [FIRST SCAN] Initializing market baseline report...")
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

                        if should_broadcast_message("baseline_report", report):
                            await listener.send_message(report, parse_mode="Markdown")
                            logger.info("✅ [FIRST SCAN] Baseline report sent")
                        else:
                            logger.info("⏭️ [FIRST SCAN] Baseline report matches last broadcast; skipping spam.")

                        snapshot_mgr.capture(
                            category="SYSTEM",
                            component="MARKET_REPORT",
                            data={"report": report},
                            tags=["periodic", "market_scan", "first_run"]
                        )

                        # Capture full scan results for TRADING category
                        snapshot_mgr.capture(
                            category="TRADING",
                            component="MARKET_SCAN_RESULTS",
                            data={
                                "timestamp": result.timestamp,
                                "total_markets": result.total_markets_scanned,
                                "winning_bets": len(result.winning_bets),
                                "trending_markets": len(result.trending_markets),
                                "competitive_markets": len(result.competitive_markets),
                                "arbitrage_opportunities": len(result.arbitrage_opportunities),
                                "sentiment": result.aggregate_sentiment,
                                "winning_bets_detail": [
                                    {
                                        "ticker": s.ticker,
                                        "side": s.side,
                                        "confidence": s.confidence,
                                        "fee_rate_bps": s.fee_rate_bps,
                                        "reason": s.reason,
                                        "market_question": s.market_question,
                                    } for s in result.winning_bets
                                ],
                            },
                            tags=["market_scan", "first_run", "gems"]
                        )
                        first_scan_completed = True

                    # ─── CONTINUOUS MONITORING (Every iteration) ───

                    # Monitor sentiment changes
                    sentiment = result.aggregate_sentiment.get("sentiment", "NEUTRAL")
                    if sentiment != last_sentiment:
                        mood = result.aggregate_sentiment.get("bullish_pct", 50)
                        msg = (
                            f"🌍 *Market Feeling Update*\n"
                            f"Feeling: `{sentiment}`\n"
                            f"Bullish share: `{mood:.1f}%`"
                        )
                        if should_broadcast_message("market_feeling", msg):
                            await listener.send_message(
                                msg,
                                parse_mode="Markdown",
                            )
                        last_sentiment = sentiment

                    # Record features for training pipeline
                    await run_blocking(
                        "record scanner features",
                        market_scanner.record_features,
                        store,
                        timeout=30.0,
                    )

                    # Broadcast market analysis
                    await broadcaster.scan_and_broadcast()

                    # ─── PERIODIC CRYPTO INTELLIGENCE (First scan + time-based) ───
                    now = datetime.now(timezone.utc).timestamp()
                    should_run_intelligence = (
                        is_first_scan or
                        (now - last_crypto_intelligence_at) >= crypto_intelligence_interval
                    )

                    if should_run_intelligence:
                        logger.info(f"📊 [CRYPTO INTELLIGENCE] Running analysis...")
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
                            if should_broadcast_message("crypto_intelligence", intelligence_text):
                                sent = await listener.send_message(intelligence_text)
                                if sent:
                                    last_crypto_intelligence_at = now
                                    logger.info(f"✅ [CRYPTO INTELLIGENCE] Report sent and cached")
                            else:
                                last_crypto_intelligence_at = now
                                logger.info(f"⏭️ [CRYPTO INTELLIGENCE] Report matches last broadcast; skipping spam.")
                            snapshot_mgr.capture(
                                category="SYSTEM",
                                component="CRYPTO_INTELLIGENCE",
                                data=intelligence_report.to_dict(),
                                tags=["periodic", "crypto_intelligence"],
                            )

                    # ─── WINNING BETS ALERTS + AUTO-TRADE (Every iteration if present) ───
                    if result.winning_bets:
                        alert = format_winning_bets_alert(result.winning_bets[:3])
                        if alert and should_broadcast_message("winning_bets_alert", alert):
                            await listener.send_message(alert, parse_mode="Markdown")

                        # Auto-trade: push winning bets to orchestrator for execution
                        for bet in result.winning_bets:
                            try:
                                # Dynamically subscribe to CLOB feed for this market if not already present
                                if clob_listener:
                                    clob_listener.subscribe([bet.ticker])

                                signal = {
                                    "ticker": bet.ticker,
                                    "side": bet.side,
                                    "price": bet.price,
                                    "confidence": bet.confidence,
                                    "reason": bet.reason,
                                    "market_question": bet.market_question,
                                    "market_slug": bet.market_slug,
                                    "source": "market_scanner",
                                    "token_id": bet.ticker,
                                    "size": 0.0,  # Let risk engine compute
                                }
                                await orchestrator.on_signal(signal)
                                logger.info(f"📈 Auto-trade signal pushed: {bet.side} {bet.ticker} ({bet.confidence:.0%} confidence)")
                            except Exception as e:
                                logger.warning(f"Failed to auto-trade winning bet {bet.ticker}: {e}")

                        # Capture winning bets in TRADING category
                        snapshot_mgr.capture(
                            category="TRADING",
                            component="WINNING_BETS",
                            data={
                                "timestamp": result.timestamp,
                                "count": len(result.winning_bets),
                                "gems": [
                                    {
                                        "ticker": s.ticker,
                                        "confidence": s.confidence,
                                        "price": s.price,
                                        "fee_rate_bps": s.fee_rate_bps,
                                        "reason": s.reason,
                                        "market_question": s.market_question,
                                        "direction": s.direction,
                                    } for s in result.winning_bets[:5]
                                ],
                            },
                            tags=["winning_bets", "gems", "high_confidence"]
                        )
                        trending = format_scan_report(result)
                        if len(trending) > 100 and should_broadcast_message("scan_report", trending):
                            await listener.send_message(trending, parse_mode="Markdown")
                else:
                    logger.warning("Scan returned 0 markets — check API connectivity")

            except Exception as e:
                logger.error(f"❌ [MARKET SCAN] Failed: {e}")
            finally:
                await asyncio.sleep(SCAN_INTERVAL_SECONDS)

    async def _hmm_training_loop() -> None:
        """Trains HMM on real Polymarket probability returns every 6h."""
        try:
            import numpy as np
            from datetime import datetime, timezone, timedelta
            lookback_hours = 336  # 14 days
            since = (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).timestamp()
            markets = await run_blocking(
                "hmm training data fetch",
                market_scanner.client.list_markets,
                limit=50,
                sort_by="volume",
                timeout=30.0,
            )
            if not markets:
                logger.warning("HMM training: no markets fetched")
                return
            prob_series: list[float] = []
            for m in markets[:10]:
                try:
                    ob = await run_blocking(
                        f"orderbook {m.id}",
                        market_scanner.client.get_order_book,
                        m.id,
                        timeout=15.0,
                    )
                    mid = float(ob.get("midpoint", 0.5) or 0.5)
                    prob_series.append(mid)
                except Exception:
                    pass
            if len(prob_series) >= 20:
                returns = np.diff(np.log(np.clip(prob_series, 0.01, 0.99)))
                returns = returns[np.isfinite(returns)]
                if len(returns) >= 10:
                    hmm.fit(returns)
                    logger.info(f"✅ HMM retrained on {len(returns)} returns from {len(prob_series)} markets")
                else:
                    logger.warning(f"HMM training: insufficient returns ({len(returns)} < 10)")
            else:
                logger.warning(f"HMM training: insufficient prob series ({len(prob_series)} < 20)")
        except Exception as e:
            logger.error(f"HMM training error: {e}")
    runner.register_job("HMM_Training", _hmm_training_loop, interval_sec=21600.0)

    async def _sltp_monitoring_loop() -> None:
        """Monitors open positions for stop-loss/take-profit."""
        try:
            if ledger is None:
                return
            open_positions = ledger.get_open_positions()
            if not open_positions:
                return
            current_prices: dict[str, float] = {}
            for pos in open_positions:
                ticker = pos.get("ticker", "")
                if ticker in current_prices:
                    continue
                try:
                    ob = await run_blocking(
                        f"sltp orderbook {ticker}",
                        market_scanner.client.get_order_book,
                        ticker,
                        timeout=10.0,
                    )
                    mid = float(ob.get("midpoint", 0.0) or ob.get("price", 0.0))
                    if mid > 0:
                        current_prices[ticker] = mid
                except Exception:
                    pass
            if not current_prices:
                return
            due = ledger.get_positions_due_for_exit(current_prices)
            for pos in due:
                reason = pos.get("exit_reason", "unknown")
                ticker = pos.get("ticker", "")
                pos_id = pos.get("position_id", "")
                entry = float(pos.get("entry_price", 0.0))
                exit_p = float(pos.get("exit_price", 0.0))
                pnl_pct = ((exit_p - entry) / entry * 100) if entry > 0 else 0.0

                # Determine target exit side: opposite of the entry side
                entry_side = pos.get("side", "BUY").upper()
                exit_side = "SELL" if entry_side == "BUY" else "BUY"
                size = float(pos.get("size", 0.0))

                if size > 0:
                    logger.info(f"🔄 [SL/TP TRIGGERED] Closing position on exchange: {exit_side} {size} {ticker} @ {exit_p}")
                    success = False
                    try:
                        exec_res = await passive_executor.execute(
                            ticker=ticker,
                            side=exit_side,
                            price=exit_p,
                            size=size,
                            override_strict_maker=True,
                        )
                        logger.info(f"SL/TP exchange execution result: {exec_res}")
                        if exec_res.get("status") in ("FILLED", "TAKER_FILLED"):
                            success = True
                        else:
                            logger.error(f"SL/TP exchange order failed or was rejected: {exec_res}")
                    except Exception as exec_err:
                        logger.error(f"Failed to execute SL/TP close on exchange: {exec_err}")

                    if not success:
                        warn_msg = (
                            f"⚠️ *WARNING: SL/TP CLOSURE FAILED*\n"
                            f"Ticker: `{ticker}`\n"
                            f"Exit Side: `{exit_side}` | Size: `{size}`\n"
                            f"Exchange order was NOT filled (rejected or failed).\n"
                            f"The position remains OPEN on Polymarket. Please close manually!"
                        )
                        try:
                            await listener.send_message(warn_msg, parse_mode="Markdown")
                        except Exception:
                            pass
                        continue

                ledger.close_position(pos_id, exit_price=exit_p)
                msg = (
                    f"⏹ *Position Closed: {reason}*\n"
                    f"Ticker: `{ticker}`\n"
                    f"Entry: `${entry:.4f}` → Exit: `${exit_p:.4f}`\n"
                    f"PnL: `{pnl_pct:+.2f}%`"
                )
                try:
                    await listener.send_message(msg, parse_mode="Markdown")
                except Exception:
                    pass
                logger.info(f"SL/TP closed {pos_id}: {reason} ({pnl_pct:+.2f}%)")
        except Exception as e:
            logger.error(f"SL/TP monitoring error: {e}")

    runner.register_job("SLTP_Monitoring", _sltp_monitoring_loop, interval_sec=10.0)

    ws_url = secrets.get("WS_URL") or os.getenv("WS_URL", "")
    polygon_rpc = secrets.get("POLYGON_RPC_URL") or os.getenv("POLYGON_RPC_URL") or os.getenv("RPC_URL", "")

    polymarket_monitor = None
    onchain_monitor_enabled = _env_bool("POLYMARKET_ONCHAIN_MONITOR_ENABLED", False)
    if onchain_monitor_enabled and ws_url:
        target_wallet = os.getenv("TARGET_WALLET", "")
        polymarket_monitor = PolymarketMonitor(
            on_signal=orchestrator.on_signal,
            target_wallet=target_wallet or None,
            ws_url=ws_url,
            rpc_url=polygon_rpc,
        )
        logger.info(f"Polymarket on-chain monitor: {'enabled (target=' + target_wallet + ')' if target_wallet else 'enabled (ALL wallets)'}")
    elif onchain_monitor_enabled:
        logger.info("Polymarket on-chain monitor: disabled (set WS_URL to enable)")
    else:
        logger.info("Polymarket on-chain monitor: disabled (POLYMARKET_ONCHAIN_MONITOR_ENABLED=0)")

    health_supervisor = HealthSupervisorAgent(
        feature_store=store,
        ledger=ledger,
        wallet_manager=PolymarketWalletManager(
            vault_handler=container.vault,
            polygon_rpc_url=polygon_rpc,
        ),
        data_archiver=DataArchiver(
            db_path=os.getenv(
                "API_FEATURE_STORE_PATH",
                os.path.join(os.getenv("DATA_PATH", "user_data/data"), "feature_store.duckdb"),
            ),
        ),
        broadcaster=orchestrator.broadcaster,
        secrets=secrets,
        config=HealthSupervisorConfig(
            staleness_threshold_seconds=float(os.getenv("HEALTH_STALENESS_THRESHOLD_SECONDS", os.getenv("MAX_POLYMARKET_STALENESS_SECONDS", "60.0"))),
            memory_warning_mb=float(os.getenv("HEALTH_MEMORY_WARNING_MB", os.getenv("MAX_MEMORY_MB_THRESHOLD", "1024"))),
            memory_critical_mb=float(os.getenv("HEALTH_MEMORY_CRITICAL_MB", str(float(os.getenv("HEALTH_MEMORY_WARNING_MB", os.getenv("MAX_MEMORY_MB_THRESHOLD", "1024"))) * 1.5))),
            wallet_reconciliation_interval_seconds=float(os.getenv("HEALTH_WALLET_RECONCILIATION_INTERVAL_SECONDS", "3600")),
            maintenance_interval_seconds=float(os.getenv("HEALTH_MAINTENANCE_INTERVAL_SECONDS", "86400")),
            check_interval_seconds=float(os.getenv("HEALTH_CHECK_INTERVAL_SECONDS", "5")),
            wallet_drift_tolerance_usd=float(os.getenv("HEALTH_WALLET_DRIFT_TOLERANCE_USD", os.getenv("MAX_WALLET_DRIFT_USDC", "0.01"))),
            disk_usage_warning_bytes=int(os.getenv("HEALTH_DISK_WARNING_BYTES", "5000000000")),
            disk_usage_critical_bytes=int(os.getenv("HEALTH_DISK_CRITICAL_BYTES", "8000000000")),
        ),
    )
    health_sidecar = HealthMonitorAgent(
        config=HealthMonitorConfig(
            heartbeat_interval_seconds=float(os.getenv("HEALTH_SIDE_CAR_HEARTBEAT_SECONDS", "30")),
            duckdb_prune_interval_seconds=float(os.getenv("HEALTH_SIDE_CAR_DUCKDB_PRUNE_SECONDS", "86400")),
            memory_check_interval_seconds=float(os.getenv("HEALTH_SIDE_CAR_MEMORY_CHECK_SECONDS", "60")),
            max_memory_rss_mb=float(os.getenv("HEALTH_SIDE_CAR_MAX_MEMORY_RSS_MB", os.getenv("MAX_MEMORY_MB_THRESHOLD", "1024"))),
            enable_ledger_reconciliation=_env_bool("HEALTH_SIDE_CAR_ENABLE_LEDGER_RECONCILIATION", True),
            enable_feature_store_maintenance=_env_bool("HEALTH_SIDE_CAR_ENABLE_FEATURE_STORE_MAINTENANCE", True),
        ),
        feature_store=store,
        ledger=ledger,
        broadcaster=orchestrator.broadcaster,
    )

    user_ws_coro = None
    if secrets.get("CLOB_API_KEY") and secrets.get("CLOB_API_SECRET") and secrets.get("CLOB_API_PASSPHRASE"):
        try:
            user_creds = ApiCreds(
                api_key=secrets["CLOB_API_KEY"],
                api_secret=secrets["CLOB_API_SECRET"],
                api_passphrase=secrets["CLOB_API_PASSPHRASE"]
            )
            user_listener = UserCLOBListener(api_creds=user_creds)

            async def on_user_event(event: dict):
                event_type = event.get("event_type")
                if event_type == "order":
                    # Polymarket V2 sometimes sends order status updates
                    if event.get("status") == "CLOSED":
                        logger.info(f"✅ Order {event.get('order_id')} fully filled/closed.")
                elif event_type == "trade":
                    # This is a fill event
                    order_id = event.get("order_id")
                    size = float(event.get("size", 0.0))
                    price = float(event.get("price", 0.0))
                    logger.info(f"💰 Trade Execution (Fill): {size} @ {price} for order {order_id}")
                    if ledger:
                        success = ledger.update_position_fill(
                            exchange_order_id=order_id,
                            filled_qty=size,
                            execution_price=price,
                        )
                        if success:
                            msg = f"⚡ *Live Fill Detected*\nOrder: `{order_id[:8]}...`\nSize: `{size}` @ `{price}`"
                            await listener.send_message(msg, parse_mode="Markdown")

            user_listener.on_event = on_user_event
            user_ws_coro = user_listener.run()
            logger.info("✅ User CLOB listener initialized and ready for streaming.")
        except Exception as e:
            logger.error(f"User CLOB listener initialization failed: {e}")

    await _run_services_loop(
        listener=listener,
        clob_feed_coro=live_clob_feed_coro,
        user_ws_coro=user_ws_coro,
        polymarket_monitor=polymarket_monitor,
        health_supervisor=health_supervisor,
        health_sidecar=health_sidecar,
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

    # Exclusive Priority: CLI Argument > Environment Variable > Database (Ledger) > Fallback ("PAPER")
    resolved_mode = None
    if args.mode is not None:
        resolved_mode = args.mode
    elif real_env:
        resolved_mode = "PROD"
    elif paper_env:
        resolved_mode = "PAPER"
    else:
        try:
            from ledger.ledger_db import Ledger
            from core.autonomous_mode_controller import select_autonomous_execution_mode
            startup_ledger = Ledger()
            decision = select_autonomous_execution_mode(startup_ledger)
            resolved_mode = decision.mode
            logger.info(
                "Autonomous execution mode selected: `%s` (%s)",
                resolved_mode,
                decision.reason,
            )
        except Exception as e:
            logger.debug(f"Failed to resolve autonomous execution mode: {e}")
            resolved_mode = "PAPER"

    try:
        require_production_confirmation(resolved_mode)
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
