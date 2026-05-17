import asyncio
import logging
import time
import numpy as np
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone

logger = logging.getLogger("MLDriftMonitor")


class MLDriftMonitorAgent:
    """
    Agent de surveillance du drift ML.
    Calcule PSI et divergence KL sur les features microstructurelles.
    """

    def __init__(self, mlops_engine=None):
        self.mlops = mlops_engine
        self._running = False
        self._check_interval = 60
        self._tickers = ["BTC", "ETH", "SOL", "TRUMP", "META"]
        self._baseline_window = 500

    async def start(self, tickers: List[str] = None, interval: float = 60.0):
        if tickers:
            self._tickers = tickers
        self._check_interval = interval
        self._running = True

        logger.info(f"🚀 ML Drift Monitor started for {self._tickers}")
        asyncio.create_task(self._monitor_loop())

    async def stop(self):
        self._running = False
        logger.info("🛑 ML Drift Monitor stopped")

    async def _monitor_loop(self):
        while self._running:
            for ticker in self._tickers:
                try:
                    await self._check_drift(ticker)
                except Exception as e:
                    logger.error(f"Drift check error for {ticker}: {e}")

            await asyncio.sleep(self._check_interval)

    async def _check_drift(self, ticker: str):
        live_features = self._generate_synthetic_features(ticker)

        if self.mlops:
            report = self.mlops.detecter_drift(ticker, live_features)

            if report.drift_detected:
                logger.warning(f"⚠️ DRIFT DETECTED: {ticker} - {report.severity} - {report.recommendation}")

                if report.severity == "CRITICAL":
                    await self._trigger_retraining(ticker, report)
        else:
            logger.debug(f"No MLOps engine for {ticker}")

    def _generate_synthetic_features(self, ticker: str) -> np.ndarray:
        np.random.seed(hash(ticker) % 2**32)
        return np.random.randn(self._baseline_window, 8)

    async def _trigger_retraining(self, ticker: str, report):
        logger.warning(f"🔄 TRIGGERING RETRAINING for {ticker} due to {report.severity} drift")

    def get_status(self) -> Dict[str, Any]:
        if self.mlops:
            return self.mlops.get_drift_summary()
        return {"status": "no_mlops_engine"}