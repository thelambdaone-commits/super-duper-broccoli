import logging
import os
from typing import Optional

from core.freqai_engine import FreqAIEngine
from core.portfolio_risk_engine import PortfolioRiskEngine
from core.services.metrics_exporter import ExecutionMetricsExporter
from execution.passive_executor import PassiveExecutor
from ledger.ledger_db import Ledger
from user_data.strategies.hmm_filter import HMMRegimeFilter
from utils.feature_store import FeatureStore
from utils.notifier import TelegramNotifier
from utils.vault_handler import VaultHandler

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
        
        self.notifier = TelegramNotifier(
            bot_token=self.secrets.get("TELEGRAM_BOT_TOKEN"),
            chat_id=os.getenv("CHAT_ID"),
        )
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
        
        logger.info("ServiceContainer: All core services initialized.")

    @classmethod
    def get_instance(cls) -> "ServiceContainer":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

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
