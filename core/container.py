import logging
import os
from typing import Optional, TYPE_CHECKING

from core.freqai_engine import FreqAIEngine
from core.portfolio_risk_engine import PortfolioRiskEngine
from core.services.metrics_exporter import ExecutionMetricsExporter
from core.services.history_access_service import HistoryAccessService
from core.services.predictive_gate import PredictiveGateConfig, PredictiveGateService
from core.services.trade_notification_service import TradeNotificationService
from execution.passive_executor import PassiveExecutor
from ledger.ledger_db import Ledger
from user_data.strategies.hmm_filter import HMMRegimeFilter
from utils.feature_store import FeatureStore
from utils.notifier import TelegramNotifier
from utils.vault_handler import VaultHandler

if TYPE_CHECKING:
    from models.volatility_surface import VolSurfaceAdapter
    from utils.earnings_sentiment_pipeline import EarningsSentimentPipeline
    from utils.chart_pattern_detector import ChartPatternDetector
    from utils.sentiment_ensemble import SentimentEnsemble
    from models.portfolio import PortfolioOptimizer
    from utils.macro_intelligence import MacroIntelligence
    from engine.backtest import Backtester
    from utils.feature_factory import FeatureFactory

logger = logging.getLogger("ServiceContainer")

class ServiceContainer:
    _instance: Optional["ServiceContainer"] = None

    def __init__(self) -> None:
        self.vault = VaultHandler()
        self.secrets = self.vault.fetch_quantum_secrets()

        self.ledger = Ledger()

        # Resolve active proxy/funder wallet
        from utils.credential_manager import CredentialManager
        funder = None
        try:
            mgr = CredentialManager()
            chat_id = os.getenv("CHAT_ID")
            if chat_id:
                for wtype in ["import", "default"]:
                    try:
                        u_data = mgr.load_user(chat_id, wtype)
                        if u_data.get("proxy_wallet"):
                            funder = u_data["proxy_wallet"]
                            break
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"Unable to load active proxy wallet: {e}")

        self.freqai = FreqAIEngine(
            private_key=self.secrets["CLOB_PRIVATE_KEY"],
            api_key=self.secrets["CLOB_API_KEY"],
            api_secret=self.secrets["CLOB_API_SECRET"],
            api_passphrase=self.secrets["CLOB_API_PASSPHRASE"],
            funder=funder,
        )
        self.hmm = HMMRegimeFilter()
        self.risk = PortfolioRiskEngine(ledger=self.ledger, hmm_filter=self.hmm)
        self.risk.rehydrate_from_ledger(self.ledger)

        # Determine store path
        default_data_dir = os.getenv("DATA_PATH", "user_data/data")
        api_store_path = os.getenv(
            "API_FEATURE_STORE_PATH",
            os.path.join(default_data_dir, "feature_store.duckdb"),
        )
        self.store = FeatureStore(db_path=api_store_path)
        self.history = HistoryAccessService(self.store, self.ledger)
        self.store.history_access = self.history
        self.predictive_gate_service = PredictiveGateService(
            config=PredictiveGateConfig(min_edge_threshold=0.07),
            feature_store=self.store,
        )

        self.notifier = TelegramNotifier(
            bot_token=self.secrets.get("TELEGRAM_BOT_TOKEN"),
            chat_id=os.getenv("TRADE_ALERT_CHAT_ID") or os.getenv("CHAT_ID"),
        )
        self.trade_notifications = TradeNotificationService(self.notifier)
        self.metrics_exporter = ExecutionMetricsExporter(
            config={
                "metrics_log_path": os.getenv(
                    "EXECUTION_METRICS_LOG_PATH",
                    os.path.join(default_data_dir, "execution_metrics.jsonl"),
                )
            }
        )

        self.executor = PassiveExecutor(
            freqai=self.freqai,
            ledger=self.ledger,
            maker_timeout_calibrator=self._make_timeout_calibrator(),
        )

        # New module instances (lazy init with try/except)
        self.vol_surface: Optional["VolSurfaceAdapter"] = None
        self.earnings: Optional["EarningsSentimentPipeline"] = None
        self.chart_detector: Optional["ChartPatternDetector"] = None
        self.sentiment_ensemble: Optional["SentimentEnsemble"] = None
        self.portfolio_opt: Optional["PortfolioOptimizer"] = None
        self.macro: Optional["MacroIntelligence"] = None
        self.backtester: Optional["Backtester"] = None
        self.feature_factory: Optional["FeatureFactory"] = None
        self._init_new_modules()

        logger.info("ServiceContainer: All core services initialized.")

    def _init_new_modules(self) -> None:
        try:
            from models.volatility_surface import VolSurfaceAdapter
            self.vol_surface = VolSurfaceAdapter()
        except Exception as e:
            logger.warning(f"VolSurfaceAdapter init failed: {e}")
        try:
            from utils.earnings_sentiment_pipeline import EarningsSentimentPipeline
            self.earnings = EarningsSentimentPipeline(
                gemini_api_key=self.secrets.get("GEMINI_API_KEY"),
                use_huggingface=True,
            )
        except Exception as e:
            logger.warning(f"EarningsSentimentPipeline init failed: {e}")
        try:
            from utils.chart_pattern_detector import ChartPatternDetector
            self.chart_detector = ChartPatternDetector()
        except Exception as e:
            logger.warning(f"ChartPatternDetector init failed: {e}")
        try:
            from utils.sentiment_ensemble import SentimentEnsemble
            self.sentiment_ensemble = SentimentEnsemble(use_vader=True, use_finbert=True)
        except Exception as e:
            logger.warning(f"SentimentEnsemble init failed: {e}")
        try:
            from models.portfolio import PortfolioOptimizer
            self.portfolio_opt = PortfolioOptimizer(method="mean_variance")
        except Exception as e:
            logger.warning(f"PortfolioOptimizer init failed: {e}")
        try:
            from utils.macro_intelligence import MacroIntelligence
            self.macro = MacroIntelligence()
        except Exception as e:
            logger.warning(f"MacroIntelligence init failed: {e}")
        try:
            from engine.backtest import Backtester
            self.backtester = Backtester(initial_capital=10000.0)
        except Exception as e:
            logger.warning(f"Backtester init failed: {e}")
        self.feature_factory = None
        logger.info("FeatureFactory initialization deferred until OHLCV data is available.")

    @classmethod
    def get_instance(cls) -> "ServiceContainer":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def sync_real_capital(self) -> None:
        """Syncs the ledger with real-world capital if RPC is available."""
        from core.wallet_manager import PolymarketWalletManager

        wallet_address = os.getenv("POLYMARKET_WALLET_ADDRESS") or os.getenv("WALLET_ADDRESS")
        proxy_address = os.getenv("POLYMARKET_PROXY_WALLET_ADDRESS") or os.getenv("PROXY_WALLET_ADDRESS")
        rpc_url = self.secrets.get("POLYGON_RPC_URL") or os.getenv("POLYGON_RPC_URL")

        if not wallet_address or not rpc_url:
            logger.warning("Capital sync skipped: WALLET_ADDRESS or POLYGON_RPC_URL missing.")
            return

        try:
            mgr = PolymarketWalletManager(self.vault, polygon_rpc_url=rpc_url)
            balances = await mgr.recuperer_soldes_on_chain(wallet_address, proxy_address=proxy_address)
            real_total = balances.get("usdc_balance", 0.0)

            if real_total > 0:
                self.ledger.sync_capital(real_total)
                # Re-rehydrate risk to be sure
                self.risk.rehydrate_from_ledger(self.ledger)
            else:
                logger.warning(f"Real capital reported as 0.0 for {wallet_address}. Sync aborted to prevent safety issues.")
        except Exception as e:
            logger.error(f"Failed to sync real capital: {e}")

    def _make_timeout_calibrator(self):
        from utils.regime_utils import get_regime_label
        def calibrate(ticker: str) -> float:
            label = get_regime_label(self.hmm, ticker)
            base_timeout = 5.0
            if label == "ERRATIC_VOLATILITY":
                return max(1.0, base_timeout * 0.3)
            elif label == "HIGH_TREND_VOLATILITY":
                return max(1.0, base_timeout * 0.6)
            return base_timeout
        return calibrate
