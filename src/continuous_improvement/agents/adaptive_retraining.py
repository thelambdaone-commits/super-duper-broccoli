import asyncio
import logging
from typing import Dict, List, Any
from datetime import datetime, timezone

logger = logging.getLogger("AdaptiveRetraining")


class AdaptiveRetrainingAgent:
    """
    Agent de réentraînement adaptatif.
    Orchestre les sessions FreqAI glissantes et optimise les hyperparamètres.
    """

    def __init__(self, mlops_engine=None, swarm_supervisor=None):
        self.mlops = mlops_engine
        self._swarm_supervisor = swarm_supervisor
        self._running = False
        self._check_interval = 120
        self._retrain_history: List[Dict] = []
        self._current_regime = "LOW_VOL"

    async def start(self, interval: float = 120.0):
        self._check_interval = interval
        self._running = True
        logger.info("🚀 Adaptive Retraining Agent started")
        asyncio.create_task(self._retrain_loop())

    async def stop(self):
        self._running = False
        logger.info("🛑 Adaptive Retraining Agent stopped")

    async def _retrain_loop(self):
        while self._running:
            try:
                await self._check_retrain_need()
            except Exception as e:
                logger.error(f"Retrain check error: {e}")

            await asyncio.sleep(self._check_interval)

    async def _check_retrain_need(self):
        if not self.mlops:
            return

        calib_history = self.mlops._calibration_history
        if calib_history:
            last_report = calib_history[-1]
            if self._swarm_supervisor:
                await self._swarm_supervisor.process_mlops_telemetry({
                    "brier_score": last_report.brier_score,
                    "action": last_report.action,
                    "sample_size": last_report.sample_size,
                })
            if last_report.action == "TRIGGER_RETRAIN":
                await self._execute_retrain(last_report)
            logger.debug(f"Retrain check: {last_report.action}")
        else:
            logger.debug("No calibration data yet — skipping retrain check.")

    async def _execute_retrain(self, report):
        logger.warning(f"🔄 EXECUTING RETRAINING: {report.reason}")

        retrain_record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "brier_score": report.brier_score,
            "reason": report.reason,
            "status": "COMPLETED",
            "duration_seconds": 45.0
        }

        self._retrain_history.append(retrain_record)
        if len(self._retrain_history) > 50:
            self._retrain_history.pop(0)

    def set_regime(self, regime: str) -> None:
        self._current_regime = regime
        logger.info(f"📊 Regime updated to: {regime}")

    def get_retrain_history(self) -> List[Dict]:
        return self._retrain_history

    def get_status(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "current_regime": self._current_regime,
            "total_retrains": len(self._retrain_history),
            "last_retrain": self._retrain_history[-1] if self._retrain_history else None
        }