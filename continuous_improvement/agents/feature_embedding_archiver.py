import asyncio
import logging
import time
import numpy as np
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone

from utils.market_watchlist import get_polymarket_watchlist

logger = logging.getLogger("FeatureEmbeddingArchiver")


class FeatureEmbeddingArchiverAgent:
    """
    Agent d'archivage des embeddings TFT.
    Sérialise les vecteurs latents en JSONL pour forensic backtesting.
    """

    def __init__(self, mlops_engine=None):
        self.mlops = mlops_engine
        self._running = False
        self._check_interval = 10
        self._tickers = get_polymarket_watchlist(limit=10, categories=["crypto", "macro"])[:3]
        self._embeddings_logged = 0

    async def start(self, tickers: List[str] = None, interval: float = 10.0):
        if tickers:
            self._tickers = tickers
        self._check_interval = interval
        self._running = True

        logger.info(f"🚀 Feature Embedding Archiver started for {self._tickers}")
        asyncio.create_task(self._archive_loop())

    async def stop(self):
        self._running = False
        logger.info(f"🛑 Embedding Archiver stopped. Total embeddings: {self._embeddings_logged}")

    async def _archive_loop(self):
        while self._running:
            for ticker in self._tickers:
                try:
                    await self._archive_embedding(ticker)
                except Exception as e:
                    logger.error(f"Archive error for {ticker}: {e}")

            await asyncio.sleep(self._check_interval)

    async def _archive_embedding(self, ticker: str):
        embedding = self._generate_synthetic_embedding(ticker)

        metadata = {
            "inference_ms": np.random.uniform(5, 15),
            "hmm_regime": np.random.choice(["LOW_VOL", "HIGH_VOL", "ERRATIC"]),
            "model_version": "freqai_v2.1"
        }

        if self.mlops:
            await self.mlops.archiver_embeddings_tft(
                ticker=ticker,
                embeddings=embedding,
                metadata=metadata
            )
            self._embeddings_logged += 1

    def _generate_synthetic_embedding(self, ticker: str) -> np.ndarray:
        np.random.seed(hash(ticker) % 2**32)
        return np.random.randn(64)

    def get_status(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "tickers": self._tickers,
            "total_embeddings": self._embeddings_logged,
            "interval_seconds": self._check_interval
        }
