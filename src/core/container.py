import logging
import os
from typing import Optional, TYPE_CHECKING

from polymarket.execution.freqai_engine import FreqAIEngine
from services.portfolio_risk_engine import PortfolioRiskEngine
from services.metrics_exporter import ExecutionMetricsExporter
from services.history_access_service import HistoryAccessService
from services.predictive_gate import PredictiveGateConfig, PredictiveGateService
from services.trade_notification_service import TradeNotificationService
from polymarket.execution.passive_executor import PassiveExecutor
from database.ledger_db import Ledger
from strategies.hmm_filter import HMMRegimeFilter
from utils.feature_store import FeatureStore
from utils.notifier import TelegramNotifier
from utils.vault_handler import VaultHandler

if TYPE_CHECKING:
    from schemas.volatility import VolSurfaceAdapter
    from utils.earnings_sentiment_pipeline import EarningsSentimentPipeline
    from utils.chart_pattern_detector import ChartPatternDetector
    from utils.sentiment_ensemble import SentimentEnsemble
    from schemas.optimization import PortfolioOptimizer
    from utils.macro_intelligence import MacroIntelligence
    from core.backtest import Backtester
    from utils.feature_factory import FeatureFactory

logger = logging.getLogger("ServiceContainer")

class ServiceContainer:
    _instance: Optional["ServiceContainer"] = None

    def __init__(self) -> None:
        self.vault = VaultHandler()
        self.secrets = self._load_secrets()
        self.ledger = Ledger()
        self.freqai = self._build_freqai_engine()
        self.hmm = HMMRegimeFilter()
        self.risk = self._build_risk_engine()
        self.risk.rehydrate_from_ledger(self.ledger)
        self.store = self._build_feature_store()
        self.history = HistoryAccessService(self.store, self.ledger)
        self.store.history_access = self.history
        from utils.config_loader import TRADING_PARAMS
        min_edge = float(TRADING_PARAMS.get("min_edge_threshold", 0.02))
        self.predictive_gate_service = PredictiveGateService(
            config=PredictiveGateConfig(min_edge_threshold=min_edge),
            feature_store=self.store,
        )
        self.notifier = self._build_notifier()
        self.trade_notifications = TradeNotificationService(self.notifier)
        self.wallet_manager = self._build_wallet_manager()
        self.metrics_exporter = self._build_metrics_exporter()
        self.executor = self._build_executor()

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

        logger.info("ServiceContainer: All services initialized.")

    def _load_secrets(self) -> dict[str, str]:
        secrets = self.vault.fetch_quantum_secrets()
        secrets.update(os.environ)
        return secrets

    def _resolve_funder_wallet(self) -> str | None:
        funder = self.secrets.get("POLYMARKET_PROXY_WALLET_ADDRESS")
        if funder:
            return funder
        from utils.credential_manager import CredentialManager

        try:
            mgr = CredentialManager()
            chat_id = os.getenv("CHAT_ID")
            if chat_id:
                for wtype in ["import", "default"]:
                    try:
                        u_data = mgr.load_user(chat_id, wtype)
                        if u_data.get("proxy_wallet"):
                            return u_data["proxy_wallet"]
                    except Exception:
                        continue
        except Exception as e:
            logger.warning(f"Unable to load active proxy wallet: {e}")
        return None

    def _build_freqai_engine(self) -> FreqAIEngine:
        return FreqAIEngine(
            private_key=self.secrets["CLOB_PRIVATE_KEY"],
            api_key=self.secrets["CLOB_API_KEY"],
            api_secret=self.secrets["CLOB_API_SECRET"],
            api_passphrase=self.secrets["CLOB_API_PASSPHRASE"],
            funder=self._resolve_funder_wallet(),
        )

    def _build_risk_engine(self) -> PortfolioRiskEngine:
        return PortfolioRiskEngine(ledger=self.ledger, hmm_filter=self.hmm)

    def _build_feature_store(self) -> FeatureStore:
        default_data_dir = os.getenv("DATA_PATH", "data")
        api_store_path = os.getenv("API_FEATURE_STORE_PATH", os.path.join(default_data_dir, "feature_store.duckdb"))
        return FeatureStore(db_path=api_store_path)

    def _build_notifier(self) -> TelegramNotifier:
        return TelegramNotifier(
            bot_token=self.secrets.get("TELEGRAM_BOT_TOKEN"),
            chat_id=os.getenv("TRADE_ALERT_CHAT_ID") or os.getenv("CHAT_ID"),
        )

    def _build_wallet_manager(self):
        from polymarket.execution.wallet_manager import PolymarketWalletManager

        return PolymarketWalletManager(
            self.vault,
            polygon_rpc_url=self.secrets.get("POLYGON_RPC_URL") or os.getenv("POLYGON_RPC_URL", ""),
        )

    def _build_metrics_exporter(self) -> ExecutionMetricsExporter:
        default_data_dir = os.getenv("DATA_PATH", "data")
        return ExecutionMetricsExporter(
            config={
                "metrics_log_path": os.getenv(
                    "EXECUTION_METRICS_LOG_PATH",
                    os.path.join(default_data_dir, "execution_metrics.jsonl"),
                )
            }
        )

    def _build_executor(self) -> PassiveExecutor:
        return PassiveExecutor(
            freqai=self.freqai,
            ledger=self.ledger,
            wallet_manager=self.wallet_manager,
            wallet_private_key=self.secrets.get("CLOB_PRIVATE_KEY"),
            usdc_spender_address=os.getenv("POLYMARKET_SPENDER_ADDRESS") or os.getenv("CLOB_SPENDER_ADDRESS"),
            maker_timeout_calibrator=self._make_timeout_calibrator(),
        )

    def _init_new_modules(self) -> None:
        try:
            from schemas.volatility import VolSurfaceAdapter
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
            from schemas.optimization import PortfolioOptimizer
            self.portfolio_opt = PortfolioOptimizer(method="mean_variance")
        except Exception as e:
            logger.warning(f"PortfolioOptimizer init failed: {e}")
        try:
            from utils.macro_intelligence import MacroIntelligence
            self.macro = MacroIntelligence()
        except Exception as e:
            logger.warning(f"MacroIntelligence init failed: {e}")
        try:
            from core.backtest import Backtester
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

    async def sync_real_capital(self) -> dict[str, float]:
        """Syncs the ledger with real-world capital if RPC is available."""
        from polymarket.execution.wallet_manager import PolymarketWalletManager

        wallet_address = self.secrets.get("POLYMARKET_WALLET_ADDRESS") or self.secrets.get("EOA_ADDRESS") or os.getenv("WALLET_ADDRESS")
        proxy_address = self.secrets.get("POLYMARKET_PROXY_WALLET_ADDRESS") or os.getenv("PROXY_WALLET_ADDRESS")
        rpc_url = self.secrets.get("POLYGON_RPC_URL") or os.getenv("POLYGON_RPC_URL")

        if not wallet_address or not rpc_url:
            logger.warning("Capital sync skipped: WALLET_ADDRESS or POLYGON_RPC_URL missing.")
            return {}

        try:
            mgr = PolymarketWalletManager(self.vault, polygon_rpc_url=rpc_url)
            balances = await mgr.recuperer_soldes_on_chain(wallet_address, proxy_address=proxy_address or "")
            # IMPORTANT: For CLOB trading, we only care about the balance already in pUSD (Exchange)
            # Raw USDC in the wallet cannot be traded until deposited.
            real_tradable = balances.get("pusd_exchange", 0.0)

            if real_tradable > 0:
                self.ledger.sync_capital(real_tradable)
                # Re-rehydrate risk to be sure
                self.risk.rehydrate_from_ledger(self.ledger)
            else:
                # If exchange balance is 0, we should still sync to prevent over-trading
                self.ledger.sync_capital(0.0)
                logger.warning(f"Tradable exchange balance is 0.0 for {wallet_address}. Trading will be blocked until USDC is deposited into Polymarket.")
            return balances
        except Exception as e:
            logger.error(f"Failed to sync real capital: {e}")
            return {}

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
