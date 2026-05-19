"""
RUFLO SWARM ORCHESTRATOR
========================
Chef d'orchestre central de l'essaim auto-apprenant pour trading Polymarket.

Gère:
- Communication inter-agents via bus asynchrone
- Telemetry centralisée (MLOps + Arbitrage)
- Circuit Breaker (Brier > 0.04 → PAUSE_PROD)
- Retrain glissant toutes les 4h sur marchés actifs
- Transition PAPER→PROD après 100 ticks
- Détection gaps de données critiques
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import numpy as np

try:
    import redis.asyncio as redis
except ImportError:
    redis = None

logger = logging.getLogger("RufloSwarmSupervisor")


class ExecutionMode(Enum):
    """Modes d'exécution avec transition contrôlée."""
    PAPER = "PAPER"
    PROD = "PROD"
    PAUSED = "PAUSED"  # Circuit breaker triggered


class SwarmState(Enum):
    """État global de l'essaim."""
    INITIALIZING = "INITIALIZING"
    HEALTHY = "HEALTHY"
    DRIFTING = "DRIFTING"
    CRITICAL = "CRITICAL"
    DEGRADED = "DEGRADED"


class TriggerReason(Enum):
    """Raisons de déclenchement du circuit breaker."""
    NONE = "NONE"
    BRIER_EXCEEDED = "BRIER_EXCEEDED"
    LEGGING_RISK = "LEGGING_RISK"
    DATA_GAP_CRITICAL = "DATA_GAP_CRITICAL"
    PAPER_TICKS_INSUFFICIENT = "PAPER_TICKS_INSUFFICIENT"


TELEMETRY_DIR = Path("data/swarm_telemetry")
TELEMETRY_DIR.mkdir(parents=True, exist_ok=True)


class RufloSwarmSupervisor:
    """
    Orchestrateur central de l'essaim Ruflo.
    Implémente le cycle de vie complet avec circuit breaker et transition contrôlée.
    """

    # Seuil de production
    BRIER_THRESHOLD = 0.04
    MIN_WIN_RATE = 0.58
    FRICTION_COST = 0.005
    PAPER_TICKS_REQUIRED = 100
    RETRAIN_INTERVAL_HOURS = 4

    # Data gap thresholds
    MICROFISH_MIN_RECORDS = int(os.getenv("MICROFISH_MIN_RECORDS", "100"))
    DUCKBDB_MIN_RECORDS = 500
    SENTIMENT_FALLBACK_EDGE = 0.09

    def __init__(self, mode: str = "PAPER"):
        self._mode = ExecutionMode(mode)
        self._state = SwarmState.INITIALIZING
        self._trigger_reason = TriggerReason.NONE

        # Shared memory bus pour inter-agent communication
        self._shared_memory: Dict[str, Any] = {}
        self._event_bus: asyncio.Queue = asyncio.Queue(maxsize=1000)

        # Redis distributed memory
        self._redis_url = os.getenv("REDIS_URL")
        self._redis: Optional[redis.Redis] = None
        self._redis_namespace = "quant_core_v2"
        
        try:
            config_path = Path("ruflo_config.json")
            if config_path.exists():
                with open(config_path, "r") as f:
                    config = json.load(f)
                    self._redis_namespace = config.get("shared_memory_namespace", "quant_core_v2")
        except Exception as e:
            logger.debug(f"Failed to load ruflo_config.json for Redis namespace: {e}")

        self._redis_pubsub_task: Optional[asyncio.Task] = None

        if redis and self._redis_url:
            try:
                self._redis = redis.from_url(self._redis_url, decode_responses=True)
                logger.info(f"🌐 Redis connected: {self._redis_url}")
            except Exception as e:
                logger.warning(f"⚠️ Redis connection failed: {e}. Falling back to local memory.")
                self._redis = None

        # Telemetry
        self._mlops_telemetry_path = TELEMETRY_DIR / "mlops_telemetry.jsonl"
        self._arbitrage_telemetry_path = TELEMETRY_DIR / "arbitrage_telemetry.jsonl"

        # Metrics accumulators
        self._brier_scores: list = []
        self._win_rates: list = []
        self._paper_ticks: int = 0
        self._last_retrain_time: float = time.time()

        # Data gap tracking
        self._data_gaps: Dict[str, bool] = {
            "microfish": False,
            "duckdb": False,
            "sentiment": False,
        }

        # Callbacks pour événements
        self._on_mode_change: Optional[Callable] = None
        self._on_state_change: Optional[Callable] = None
        self._on_circuit_breaker: Optional[Callable] = None

        # Sub-agents registered
        self._agents: Dict[str, Any] = {}

        # Loop de surveillance
        self._monitoring_task: Optional[asyncio.Task] = None

    @property
    def mode(self) -> str:
        return self._mode.value

    @property
    def state(self) -> str:
        return self._state.value

    @property
    def trigger_reason(self) -> str:
        return self._trigger_reason.value

    @property
    def paper_ticks(self) -> int:
        return self._paper_ticks

    @property
    def is_production_ready(self) -> bool:
        return (
            self._mode == ExecutionMode.PAPER
            and self._paper_ticks >= self.PAPER_TICKS_REQUIRED
            and self._trigger_reason == TriggerReason.NONE
            and not any(self._data_gaps.values())
        )

    def register_agent(self, agent_id: str, agent: Any) -> None:
        """Enregistre un sous-agent dans l'essaim."""
        self._agents[agent_id] = agent
        logger.info(f"✅ Agent registered: {agent_id}")

    def set_mode_change_callback(self, callback: Callable) -> None:
        self._on_mode_change = callback

    def set_state_change_callback(self, callback: Callable) -> None:
        self._on_state_change = callback

    def set_circuit_breaker_callback(self, callback: Callable) -> None:
        self._on_circuit_breaker = callback

    def write_telemetry(self, source: str, data: Dict[str, Any]) -> None:
        """Écrit la télémétrie dans un fichier JSONL partagé."""
        path = (
            self._mlops_telemetry_path
            if source == "mlops"
            else self._arbitrage_telemetry_path
        )

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": source,
            **data,
        }

        with open(path, "a") as f:
            f.write(json.dumps(entry) + "\n")

        logger.debug(f"📡 Telemetry written: {source}")

    async def process_mlops_telemetry(self, data: Dict[str, Any]) -> None:
        """
        Traite la télémétrie MLOps.
        Déclenche retrain si Brier > 0.04.
        """
        self.write_telemetry("mlops", data)

        brier = data.get("brier_score")
        if brier is not None:
            self._brier_scores.append(brier)
            logger.info(f"📊 Brier Score: {brier:.4f}")

            if brier > self.BRIER_THRESHOLD:
                await self._trigger_circuit_breaker(TriggerReason.BRIER_EXCEEDED, {
                    "brier_score": brier,
                    "threshold": self.BRIER_THRESHOLD,
                })
                return

        win_rate = data.get("win_rate")
        if win_rate is not None:
            self._win_rates.append(win_rate)
            logger.info(f"📊 Win Rate: {win_rate:.1%}")

        drift_detected = data.get("drift_detected", False)
        if drift_detected and self._should_retrain():
            await self._trigger_retrain()

    async def process_arbitrage_telemetry(self, data: Dict[str, Any]) -> None:
        """
        Traite la télémétrie Arbitrage.
        Déclenche circuit breaker si Legging Risk flaggé.
        """
        self.write_telemetry("arbitrage", data)

        legging_risk = data.get("legging_risk", False)
        kolmogorov_violation = data.get("kolmogorov_violation", False)

        if legging_risk or kolmogorov_violation:
            await self._trigger_circuit_breaker(TriggerReason.LEGGING_RISK, data)

    async def record_paper_tick(self, tick_data: Dict[str, Any]) -> None:
        """Enregistre un tick en mode paper. Transite vers PROD si 100 ticks."""
        if self._mode != ExecutionMode.PAPER:
            return

        self._paper_ticks += 1
        logger.info(f"📝 Paper tick recorded: {self._paper_ticks}/{self.PAPER_TICKS_REQUIRED}")

        if self._paper_ticks >= self.PAPER_TICKS_REQUIRED:
            if self.is_production_ready:
                await self._transition_to_prod()

    def check_data_gaps(self) -> Dict[str, Any]:
        """
        Vérifie les sources de données critiques.
        Retourne un rapport de gaps.
        """
        gaps = {}
        edge_override = None

        # Check Microfish (orderbook 3 levels)
        try:
            from utils.feature_store import FeatureStore
            store = FeatureStore()
            stats = store.get_stats()
            microfish_count = stats.get("market_microstructure", 0)
            self._data_gaps["microfish"] = microfish_count < self.MICROFISH_MIN_RECORDS
            gaps["microfish"] = {
                "present": microfish_count >= self.MICROFISH_MIN_RECORDS,
                "count": microfish_count,
                "required": self.MICROFISH_MIN_RECORDS,
            }
        except Exception as e:
            logger.warning(f"Microfish check failed: {e}")
            self._data_gaps["microfish"] = True
            gaps["microfish"] = {"present": False, "error": str(e)}

        # Check DuckDB historical
        try:
            duckdb_path = Path("data/feature_store.duckdb")
            if duckdb_path.exists():
                file_size = duckdb_path.stat().st_size
                self._data_gaps["duckdb"] = file_size < 1000
                gaps["duckdb"] = {
                    "present": file_size >= 1000,
                    "size_bytes": file_size,
                    "required_min_bytes": 1000,
                }
            else:
                self._data_gaps["duckdb"] = True
                gaps["duckdb"] = {"present": False, "error": "file not found"}
        except Exception as e:
            logger.warning(f"DuckDB check failed: {e}")
            self._data_gaps["duckdb"] = True
            gaps["duckdb"] = {"present": False, "error": str(e)}

        # Check Sentiment feeds (optional)
        sentiment_ok = True
        try:
            from utils.crypto_horizon_sentiment import CryptoHorizonSentiment
            sentiment = CryptoHorizonSentiment()
            sentiment_ok = sentiment.analyze("BTC", "1h") is not None
        except Exception as e:
            logger.warning(f"Sentiment check failed: {e}")
            sentiment_ok = False

        self._data_gaps["sentiment"] = not sentiment_ok
        gaps["sentiment"] = {"present": sentiment_ok}

        if self._data_gaps["sentiment"]:
            edge_override = self.SENTIMENT_FALLBACK_EDGE
            logger.warning(f"⚠️ Sentiment feed missing. Edge threshold raised to {edge_override}")

        if any(self._data_gaps.values()):
            logger.warning(f"⚠️ Data gaps detected: {[k for k, v in self._data_gaps.items() if v]}")

        return {
            "gaps": gaps,
            "edge_override": edge_override,
            "critical_blocking": any(
                self._data_gaps.get(k, False) for k in ["microfish", "duckdb"]
            ),
        }

    def _should_retrain(self) -> bool:
        """Détermine si un retrain est nécessaire (toutes les 4h)."""
        elapsed = time.time() - self._last_retrain_time
        return elapsed >= (self.RETRAIN_INTERVAL_HOURS * 3600)

    async def _trigger_retrain(self) -> None:
        """Déclenche le retraining des modèles."""
        logger.info("🔄 Triggering model retraining...")
        self._last_retrain_time = time.time()

        if "retrain" in self._agents:
            try:
                await self._agents["retrain"].trigger_retraining()
            except Exception as e:
                logger.error(f"Retrain failed: {e}")

    async def _trigger_circuit_breaker(self, reason: TriggerReason, data: Dict[str, Any]) -> None:
        """Déclenche le circuit breaker et passe en mode PAPER."""
        if self._mode == ExecutionMode.PAUSED:
            return

        old_mode = self._mode
        old_state = self._state

        self._trigger_reason = reason
        self._mode = ExecutionMode.PAUSED
        self._state = SwarmState.CRITICAL

        logger.critical(f"🚨 CIRCUIT BREAKER TRIGGERED: {reason.value}")
        logger.critical(f"   Data: {data}")

        if self._on_circuit_breaker:
            await self._on_circuit_breaker(reason, data)

        if old_mode != ExecutionMode.PAUSED and self._on_mode_change:
            await self._on_mode_change(ExecutionMode.PAPER)

        if old_state != self._state and self._on_state_change:
            await self._on_state_change(self._state)

    async def _transition_to_prod(self) -> None:
        """Transition contrôlée PAPER → PROD."""
        if self._mode != ExecutionMode.PAPER:
            return

        if not self.is_production_ready:
            logger.warning("Not ready for PROD transition")
            return

        old_mode = self._mode
        self._mode = ExecutionMode.PROD
        self._state = SwarmState.HEALTHY
        self._trigger_reason = TriggerReason.NONE

        logger.info("🚀 TRANSITION TO PRODUCTION MODE")

        if self._on_mode_change:
            await self._on_mode_change(ExecutionMode.PROD)

        if self._on_state_change:
            await self._on_state_change(self._state)

    async def _transition_to_paper(self) -> None:
        """Force le passage en mode PAPER."""
        if self._mode == ExecutionMode.PAPER:
            return

        old_mode = self._mode
        self._mode = ExecutionMode.PAPER
        self._paper_ticks = 0

        logger.info("📝 Transitioning to PAPER mode")

        if self._on_mode_change:
            await self._on_mode_change(ExecutionMode.PAPER)

    async def start_monitoring(self) -> None:
        """Démarre le loop de surveillance continue."""
        self._state = SwarmState.HEALTHY
        self._monitoring_task = asyncio.create_task(self._monitoring_loop())
        
        if self._redis:
            self._redis_pubsub_task = asyncio.create_task(self._redis_pubsub_listener())
            
        logger.info("✅ Swarm supervisor monitoring started")

    async def _redis_pubsub_listener(self) -> None:
        """Listen to Redis Pub/Sub and inject into local event bus/shared memory."""
        if not self._redis:
            return

        pubsub = self._redis.pubsub()
        events_channel = f"{self._redis_namespace}:events"
        mem_channel = f"{self._redis_namespace}:mem_updates"
        await pubsub.subscribe(events_channel, mem_channel)

        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        if message["channel"] == events_channel:
                            await self._event_bus.put(data)
                        elif message["channel"] == mem_channel:
                            key = data.get("key")
                            value = data.get("value")
                            if key:
                                self._shared_memory[key] = value
                    except Exception as e:
                        logger.error(f"Failed to parse Redis message: {e}")
        except asyncio.CancelledError:
            await pubsub.unsubscribe(events_channel, mem_channel)
        except Exception as e:
            logger.error(f"Redis Pub/Sub error: {e}")

    async def _monitoring_loop(self) -> None:
        """Loop de surveillance continue."""
        while True:
            try:
                await asyncio.sleep(60)

                self.check_data_gaps()

                if self._should_retrain():
                    await self._trigger_retrain()

                recent_brier = self._brier_scores[-10:] if self._brier_scores else []
                if recent_brier and np.mean(recent_brier) > self.BRIER_THRESHOLD:
                    await self._trigger_circuit_breaker(
                        TriggerReason.BRIER_EXCEEDED,
                        {"avg_brier": float(np.mean(recent_brier))}
                    )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Monitoring loop error: {e}")

    async def stop_monitoring(self) -> None:
        """Arrête le loop de surveillance."""
        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass
        
        if self._redis_pubsub_task:
            self._redis_pubsub_task.cancel()
            try:
                await self._redis_pubsub_task
            except asyncio.CancelledError:
                pass

        if self._redis:
            await self._redis.close()
            
        logger.info("🛑 Swarm supervisor stopped")

    def get_status(self) -> Dict[str, Any]:
        """Retourne le status complet de l' supervisor."""
        try:
            self.check_data_gaps()
        except Exception as e:
            logger.warning(f"Failed to check data gaps during get_status: {e}")

        return {
            "mode": self._mode.value,
            "state": self._state.value,
            "trigger_reason": self._trigger_reason.value,
            "paper_ticks": self._paper_ticks,
            "paper_ticks_required": self.PAPER_TICKS_REQUIRED,
            "production_ready": self.is_production_ready,
            "data_gaps": self._data_gaps,
            "metrics": {
                "avg_brier": float(np.mean(self._brier_scores)) if self._brier_scores else None,
                "avg_win_rate": float(np.mean(self._win_rates)) if self._win_rates else None,
                "retrain_interval_hours": self.RETRAIN_INTERVAL_HOURS,
                "time_since_retrain_hours": (time.time() - self._last_retrain_time) / 3600,
            },
            "thresholds": {
                "brier_max": self.BRIER_THRESHOLD,
                "win_rate_min": self.MIN_WIN_RATE,
                "friction_cost": self.FRICTION_COST,
            },
        }

    async def publish_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Publie un événement sur le bus (local + distribué)."""
        event = {
            "type": event_type,
            "timestamp": time.time(),
            "data": data,
        }
        
        # Ingestion locale
        await self._event_bus.put(event)

        # Diffusion distribuée
        if self._redis:
            try:
                channel = f"{self._redis_namespace}:events"
                await self._redis.publish(channel, json.dumps(event))
            except Exception as e:
                logger.error(f"📡 Redis publish failed: {e}")

    async def subscribe_events(self) -> asyncio.Queue:
        """Retourne la queue des événements pour écoute."""
        return self._event_bus

    def set_shared_value(self, key: str, value: Any) -> None:
        """Écrit dans la mémoire partagée (locale + sync-fire-and-forget Redis)."""
        self._shared_memory[key] = value
        
        if self._redis:
            try:
                # 1. Persistence de la valeur
                asyncio.create_task(self._redis.set(
                    f"{self._redis_namespace}:mem:{key}", 
                    json.dumps(value)
                ))
                # 2. Notification de mise à jour pour les autres instances
                asyncio.create_task(self._redis.publish(
                    f"{self._redis_namespace}:mem_updates",
                    json.dumps({"key": key, "value": value})
                ))
            except Exception as e:
                logger.error(f"💾 Redis set/publish failed for {key}: {e}")

    def get_shared_value(self, key: str, default: Any = None) -> Any:
        """Lit dans la mémoire partagée (locale uniquement pour performance sync)."""
        return self._shared_memory.get(key, default)

    async def get_shared_value_async(self, key: str, default: Any = None) -> Any:
        """Lit dans la mémoire partagée avec accès distribué Redis."""
        # 1. Priorité au cache local
        if key in self._shared_memory:
            return self._shared_memory[key]

        # 2. Fallback Redis
        if self._redis:
            try:
                data = await self._redis.get(f"{self._redis_namespace}:mem:{key}")
                if data:
                    val = json.loads(data)
                    # On met en cache pour les prochains accès sync
                    self._shared_memory[key] = val
                    return val
            except Exception as e:
                logger.error(f"💾 Redis get failed for {key}: {e}")
        
        return default


_supervisor_instance: Optional[RufloSwarmSupervisor] = None


def get_swarm_supervisor(mode: str = "PAPER") -> RufloSwarmSupervisor:
    """Factory pour récupérer l'instance singleton du supervisor."""
    global _supervisor_instance
    if _supervisor_instance is None:
        _supervisor_instance = RufloSwarmSupervisor(mode=mode)
    return _supervisor_instance


async def initialize_swarm_supervisor(
    mode: str = "PAPER",
    retrain_agent: Any = None,
) -> RufloSwarmSupervisor:
    """
    Initialise le supervisor avec les agents branchés.
    """
    supervisor = get_swarm_supervisor(mode=mode)

    if retrain_agent:
        supervisor.register_agent("retrain", retrain_agent)

    await supervisor.start_monitoring()

    return supervisor
