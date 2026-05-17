import asyncio
import logging
import time
import json
import os
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone

logger = logging.getLogger("ArbitrageLatencyProfiler")


class ArbitrageLatencyProfilerAgent:
    """
    Agent de profilage de latence d'arbitrage.
    Mesure le décalage temporel et ajuste les seuils de déclenchement.
    """

    def __init__(self, arbitrage_engine=None):
        self.engine = arbitrage_engine
        self._running = False
        self._check_interval = 30
        self._telemetry_file = "user_data/data/raw_stream/arbitrage_telemetry.jsonl"
        self._latency_history: List[Dict] = []

    async def start(self, interval: float = 30.0):
        self._check_interval = interval
        self._running = True
        logger.info("🚀 Arbitrage Latency Profiler started")
        asyncio.create_task(self._profiler_loop())

    async def stop(self):
        self._running = False
        logger.info("🛑 Latency Profiler stopped")

    async def _profiler_loop(self):
        while self._running:
            try:
                await self._analyze_telemetry()
            except Exception as e:
                logger.error(f"Profiling error: {e}")

            await asyncio.sleep(self._check_interval)

    async def _analyze_telemetry(self):
        if not os.path.exists(self._telemetry_file):
            return

        try:
            records = []
            with open(self._telemetry_file, "r") as f:
                for line in f:
                    if line.strip():
                        records.append(json.loads(line))

            if not records:
                return

            recent = records[-20:]

            latencies = [r.get("execution_latency_ms", 0) for r in recent]
            avg_latency = sum(latencies) / len(latencies) if latencies else 0

            profits = [r.get("realized_profit", 0) for r in recent]
            theoretical = [r.get("theoretical_spread", 0) for r in recent]

            efficiency = sum(profits) / sum(theoretical) if sum(theoretical) > 0 else 0

            logger.info(f"📊 Latency: {avg_latency:.1f}ms, Efficiency: {efficiency:.2%}")

            if self.engine:
                self.engine.ajuster_seuil_trigger(efficiency)

            self._latency_history.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "avg_latency_ms": avg_latency,
                "efficiency": efficiency,
                "sample_size": len(recent)
            })

            if len(self._latency_history) > 100:
                self._latency_history.pop(0)

        except Exception as e:
            logger.error(f"Telemetry analysis error: {e}")

    def get_status(self) -> Dict[str, Any]:
        if not self._latency_history:
            return {"running": self._running, "samples": 0}

        recent = self._latency_history[-1]
        return {
            "running": self._running,
            "avg_latency_ms": recent.get("avg_latency_ms", 0),
            "efficiency": recent.get("efficiency", 0),
            "total_samples": len(self._latency_history)
        }