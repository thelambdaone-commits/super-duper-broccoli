import os
import sys
# Inject root directory to python path for PM2 and subprocess pathing
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import asyncio
import logging
import signal
from typing import List, Optional

from core.mlops_feedback_loop import LobstarMLOpsEngine
from utils.market_watchlist import get_polymarket_watchlist

from continuous_improvement.agents.microfish_ingest import MicrofishIngestAgent
from continuous_improvement.agents.forensic_postmortem import ForensicPostMortemAgent
from continuous_improvement.agents.ml_drift_monitor import MLDriftMonitorAgent
from continuous_improvement.agents.adaptive_retraining import AdaptiveRetrainingAgent
from continuous_improvement.agents.feature_embedding_archiver import FeatureEmbeddingArchiverAgent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("AgentSwarmLauncher")


class AgentSwarmLauncher:
    """
    Orchestrateur de l'essaim d'agents pour le système Lobstar.
    Gère le cycle de vie complet des 7 agents Ruflo.
    """

    def __init__(self):
        self.microfish_interval_seconds = 15.0
        self.mlops_engine: Optional[LobstarMLOpsEngine] = None

        self.microfish_agent: Optional[MicrofishIngestAgent] = None
        self.forensic_agent: Optional[ForensicPostMortemAgent] = None
        self.drift_monitor_agent: Optional[MLDriftMonitorAgent] = None
        self.retrain_agent: Optional[AdaptiveRetrainingAgent] = None
        self.embedding_agent: Optional[FeatureEmbeddingArchiverAgent] = None

        self._running = False

    async def start_all(self, tickers: List[str] = None):
        if tickers is None:
            tickers = get_polymarket_watchlist(limit=100)

        logger.info("🚀 Starting Lobstar Agent Swarm (7 agents)...")

        from core.swarm_supervisor import get_swarm_supervisor
        self.swarm_supervisor = get_swarm_supervisor()

        self.mlops_engine = LobstarMLOpsEngine()

        def on_drift_detected(drift_data: dict):
            asyncio.create_task(self.swarm_supervisor.process_mlops_telemetry({
                "drift_detected": True,
                "ticker": drift_data.get("ticker"),
                "psi": drift_data.get("psi", 0),
                "kl": drift_data.get("kl_divergence", 0),
            }))

        self.mlops_engine.set_drift_callback(on_drift_detected)

        for ticker in tickers:
            self.mlops_engine.set_baseline(ticker, self._generate_baseline(ticker))

        self.microfish_agent = MicrofishIngestAgent()
        asyncio.create_task(self.microfish_agent.start(tickers, interval=self.microfish_interval_seconds))

        self.forensic_agent = ForensicPostMortemAgent()
        await self.forensic_agent.start()

        self.drift_monitor_agent = MLDriftMonitorAgent(mlops_engine=self.mlops_engine)
        await self.drift_monitor_agent.start(tickers=tickers, interval=300.0)

        self.retrain_agent = AdaptiveRetrainingAgent(mlops_engine=self.mlops_engine)
        await self.retrain_agent.start(interval=600.0)

        self.embedding_agent = FeatureEmbeddingArchiverAgent(mlops_engine=self.mlops_engine)
        await self.embedding_agent.start(tickers=tickers, interval=60.0)

        self._running = True
        logger.info("✅ All 7 agents started (VPS Optimized Intervals)")

    def _generate_baseline(self, ticker: str):
        import numpy as np
        np.random.seed(hash(ticker) % 2**32)
        return np.random.randn(500, 8)

    async def stop_all(self):
        logger.info("🛑 Stopping agent swarm...")

        agents = [
            self.microfish_agent,
            self.forensic_agent,
            self.drift_monitor_agent,
            self.retrain_agent,
            self.embedding_agent
        ]

        for agent in agents:
            if agent:
                await agent.stop()

        self._running = False
        logger.info("✅ All agents stopped")

    def get_status(self) -> dict:
        status = {
            "mlops": {
                "drift_summary": self.mlops_engine.get_drift_summary() if self.mlops_engine else {},
                "calibration_summary": self.mlops_engine.get_calibration_summary() if self.mlops_engine else {}
            },
            "microfish": {
                "running": self.microfish_agent is not None and self.microfish_agent._running,
            },
            "forensic": {
                "running": self.forensic_agent is not None and self.forensic_agent._running,
            },
            "drift_monitor": {
                "running": self.drift_monitor_agent is not None and self.drift_monitor_agent._running,
            },
            "retrain": self.retrain_agent.get_status() if self.retrain_agent else {},
            "embedding": self.embedding_agent.get_status() if self.embedding_agent else {},
        }

        if self.microfish_agent and self.microfish_agent._running:
            status["microfish"]["spread_stats"] = self.microfish_agent.get_spread_stats()

        if self.forensic_agent and self.forensic_agent._running:
            status["forensic"]["summary"] = self.forensic_agent.get_performance_summary()

        return status


async def main():
    launcher = AgentSwarmLauncher()

    def signal_handler(sig, frame):
        print("\n🛑 Received interrupt, stopping agents...")
        asyncio.create_task(launcher.stop_all())
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    await launcher.start_all()

    while launcher._running:
        await asyncio.sleep(60)
        status = launcher.get_status()
        logger.info(f"Agent Status: {status}")


if __name__ == "__main__":
    asyncio.run(main())
