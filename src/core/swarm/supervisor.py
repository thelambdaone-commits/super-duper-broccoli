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
import contextlib
import csv
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import numpy as np

from core.swarm.types import ExecutionMode, SwarmState, TriggerReason

try:
    import redis.asyncio as redis
except ImportError:
    redis = None

logger = logging.getLogger("RufloSwarmSupervisor")


_BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
TELEMETRY_DIR = Path(os.getenv("DATA_PATH", _BASE_DIR / "data"))
TELEMETRY_DIR.mkdir(parents=True, exist_ok=True)
SWARM_STATE_PATH = TELEMETRY_DIR / "swarm_state.json"


class RufloSwarmSupervisor:
    BRIER_THRESHOLD = 0.04
    MIN_WIN_RATE = 0.58
    FRICTION_COST = 0.005
    PAPER_TICKS_REQUIRED = 100
    RETRAIN_INTERVAL_HOURS = 4
    MICROFISH_MIN_RECORDS = int(os.getenv("MICROFISH_MIN_RECORDS", "100"))
    DUCKBDB_MIN_RECORDS = 500
    SENTIMENT_FALLBACK_EDGE = 0.09
    SENTIMENT_CHECK_TTL_SECONDS = int(os.getenv("SWARM_SENTIMENT_CHECK_TTL_SECONDS", "900"))

    def __init__(self, mode: str = "PAPER"):
        self._mode = ExecutionMode(mode)
        self._state = SwarmState.INITIALIZING
        self._trigger_reason = TriggerReason.NONE
        self._shared_memory: Dict[str, Any] = {}
        self._event_bus: asyncio.Queue = asyncio.Queue(maxsize=1000)
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

        self._mlops_telemetry_path = TELEMETRY_DIR / "mlops_telemetry.jsonl"
        self._arbitrage_telemetry_path = TELEMETRY_DIR / "arbitrage_telemetry.jsonl"
        self._brier_scores: list = []
        self._win_rates: list = []
        self._paper_ticks: int = 0
        self._last_retrain_time: float = time.time()
        self._last_market_tick_signature: dict[str, tuple[float, float, float]] = {}
        self._data_gaps: Dict[str, bool] = {
            "microfish": False,
            "duckdb": False,
            "sentiment": False,
        }
        self._last_gap_report: Dict[str, bool] = dict(self._data_gaps)
        self._last_sentiment_check_at: float = 0.0
        self._last_sentiment_ok: Optional[bool] = None
        self._on_mode_change: Optional[Callable] = None
        self._on_state_change: Optional[Callable] = None
        self._on_circuit_breaker: Optional[Callable] = None
        self._agents: Dict[str, Any] = {}
        self._monitoring_task: Optional[asyncio.Task] = None
        self._running = False
        self._load_persisted_state()

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
        if self._mode == ExecutionMode.PROD:
            return True
        return (
            self._mode == ExecutionMode.PAPER
            and self._paper_ticks >= self.PAPER_TICKS_REQUIRED
            and self._trigger_reason == TriggerReason.NONE
            and not any(self._data_gaps.values())
        )

    def register_agent(self, agent_id: str, agent: Any) -> None:
        self._agents[agent_id] = agent
        logger.info(f"✅ Agent registered: {agent_id}")

    def set_mode_change_callback(self, callback: Callable) -> None:
        self._on_mode_change = callback

    def set_state_change_callback(self, callback: Callable) -> None:
        self._on_state_change = callback

    def set_circuit_breaker_callback(self, callback: Callable) -> None:
        self._on_circuit_breaker = callback

    def write_telemetry(self, source: str, data: Dict[str, Any]) -> None:
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
        self.write_telemetry("arbitrage", data)
        legging_risk = data.get("legging_risk", False)
        kolmogorov_violation = data.get("kolmogorov_violation", False)
        if legging_risk or kolmogorov_violation:
            await self._trigger_circuit_breaker(TriggerReason.LEGGING_RISK, data)

    async def record_paper_tick(self, tick_data: Dict[str, Any]) -> None:
        if self._mode != ExecutionMode.PAPER:
            return
        self._paper_ticks += 1
        self._persist_state()
        logger.info(f"📝 Paper tick recorded: {self._paper_ticks}/{self.PAPER_TICKS_REQUIRED}")

    async def record_market_tick(self, snapshot: Dict[str, Any]) -> bool:
        if self._mode != ExecutionMode.PAPER:
            return False
        token_id = str(snapshot.get("token_id") or snapshot.get("asset_id") or "")
        if not token_id:
            return False
        best_bid = float(snapshot.get("best_bid", 0.0) or 0.0)
        best_ask = float(snapshot.get("best_ask", 0.0) or 0.0)
        mid_price = float(snapshot.get("mid_price", 0.0) or 0.0)
        signature = (round(best_bid, 6), round(best_ask, 6), round(mid_price, 6))
        previous = self._last_market_tick_signature.get(token_id)
        if previous == signature:
            return False
        self._last_market_tick_signature[token_id] = signature
        await self.record_paper_tick({
            "source": "market_ws",
            "token_id": token_id,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "mid_price": mid_price,
        })
        return True

    def warm_start_from_replay(self, replay_path: str | os.PathLike[str], *, max_ticks: int | None = None) -> int:
        path = Path(replay_path)
        if not path.exists():
            return 0
        added = 0
        target = max_ticks if max_ticks is not None else self.PAPER_TICKS_REQUIRED
        try:
            if path.suffix.lower() == ".jsonl":
                with path.open("r", encoding="utf-8") as handle:
                    for line in handle:
                        if added >= target:
                            break
                        if not line.strip():
                            continue
                        payload = json.loads(line)
                        if self._register_replay_tick(payload):
                            added += 1
            else:
                with path.open("r", encoding="utf-8", newline="") as handle:
                    reader = csv.DictReader(handle)
                    for row in reader:
                        if added >= target:
                            break
                        if self._register_replay_tick(row):
                            added += 1
        except Exception as exc:
            logger.warning("Warm-start replay import failed: %s", exc)
            return 0
        if added:
            self._paper_ticks += added
            self._persist_state()
            logger.info("♻️ Warm-started %s paper ticks from replay %s", added, path)
        return added

    def check_data_gaps(self) -> Dict[str, Any]:
        gaps = {}
        edge_override = None
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
        try:
            duckdb_path = _BASE_DIR / "data" / "feature_store.duckdb"
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
        sentiment_ok = self._get_cached_sentiment_health()
        self._data_gaps["sentiment"] = not sentiment_ok
        gaps["sentiment"] = {"present": sentiment_ok}
        if self._data_gaps["sentiment"]:
            edge_override = self.SENTIMENT_FALLBACK_EDGE
            logger.warning(f"⚠️ Sentiment feed missing. Edge threshold raised to {edge_override}")
        current_gaps = {k: v for k, v in self._data_gaps.items() if v}
        previous_gaps = {k: v for k, v in self._last_gap_report.items() if v}
        if current_gaps != previous_gaps:
            if current_gaps:
                logger.warning(f"⚠️ Data gaps detected: {list(current_gaps.keys())}")
            else:
                logger.info("✅ Data gaps cleared.")
            self._last_gap_report = dict(self._data_gaps)
        return {
            "gaps": gaps,
            "edge_override": edge_override,
            "critical_blocking": any(
                self._data_gaps.get(k, False) for k in ["microfish", "duckdb"]
            ),
        }

    def _get_cached_sentiment_health(self) -> bool:
        now = time.time()
        if (
            self._last_sentiment_ok is not None
            and (now - self._last_sentiment_check_at) < self.SENTIMENT_CHECK_TTL_SECONDS
        ):
            return self._last_sentiment_ok

        sentiment_ok = True
        try:
            from utils.crypto_horizon_sentiment import CryptoHorizonSentiment

            sentiment = CryptoHorizonSentiment()
            sentiment_ok = sentiment.analyze("BTC", "1h") is not None
        except Exception as e:
            logger.warning(f"Sentiment check failed: {e}")
            sentiment_ok = False

        self._last_sentiment_check_at = now
        self._last_sentiment_ok = sentiment_ok
        return sentiment_ok

    def _should_retrain(self) -> bool:
        elapsed = time.time() - self._last_retrain_time
        return elapsed >= (self.RETRAIN_INTERVAL_HOURS * 3600)

    async def _trigger_retrain(self) -> None:
        logger.info("🔄 Triggering model retraining...")
        self._last_retrain_time = time.time()
        if "retrain" in self._agents:
            try:
                await self._agents["retrain"].trigger_retraining()
            except Exception as e:
                logger.error(f"Retrain failed: {e}")

    async def _trigger_circuit_breaker(self, reason: TriggerReason, data: Dict[str, Any]) -> None:
        if self._mode == ExecutionMode.PAUSED:
            return
        old_state = self._state
        self._trigger_reason = reason
        self._mode = ExecutionMode.PAUSED
        self._state = SwarmState.CRITICAL
        logger.critical(f"🚨 CIRCUIT BREAKER TRIGGERED: {reason.value}")
        logger.critical(f"   Data: {data}")
        if self._on_circuit_breaker:
            await self._on_circuit_breaker(reason, data)
        if old_state != self._state and self._on_state_change:
            await self._on_state_change(self._state)

    def sync_execution_mode(self, mode: str | ExecutionMode) -> None:
        target = mode if isinstance(mode, ExecutionMode) else ExecutionMode(str(mode).upper())
        if self._mode == target:
            return
        previous = self._mode
        self._mode = target
        if target == ExecutionMode.PAPER:
            self._state = SwarmState.HEALTHY
        elif target == ExecutionMode.PROD:
            self._state = SwarmState.HEALTHY
            self._trigger_reason = TriggerReason.NONE
        self._persist_state()
        logger.info("🧭 Swarm execution mode synchronized: %s -> %s", previous.value, target.value)

    async def start_monitoring(self) -> None:
        self._state = SwarmState.HEALTHY
        self._running = True
        self._persist_state()
        self._monitoring_task = asyncio.create_task(self._monitoring_loop())
        if self._redis:
            self._redis_pubsub_task = asyncio.create_task(self._redis_pubsub_listener())
        logger.info("✅ Swarm supervisor monitoring started")

    def _register_replay_tick(self, payload: Dict[str, Any]) -> bool:
        token_id = str(payload.get("token_id") or payload.get("asset_id") or payload.get("market") or "")
        if not token_id:
            return False
        best_bid = float(payload.get("best_bid", payload.get("bid_price", 0.0)) or 0.0)
        best_ask = float(payload.get("best_ask", payload.get("ask_price", 0.0)) or 0.0)
        mid_price = float(payload.get("mid_price", payload.get("price", 0.0)) or 0.0)
        signature = (round(best_bid, 6), round(best_ask, 6), round(mid_price, 6))
        previous = self._last_market_tick_signature.get(token_id)
        if previous == signature:
            return False
        self._last_market_tick_signature[token_id] = signature
        return True

    def _load_persisted_state(self) -> None:
        try:
            if not SWARM_STATE_PATH.exists():
                return
            payload = json.loads(SWARM_STATE_PATH.read_text(encoding="utf-8"))
            self._paper_ticks = int(payload.get("paper_ticks", 0) or 0)
            mode = payload.get("mode")
            state = payload.get("state")
            if mode in {item.value for item in ExecutionMode}:
                self._mode = ExecutionMode(mode)
            if state in {item.value for item in SwarmState}:
                self._state = SwarmState(state)
        except Exception as exc:
            logger.warning("Failed to load persisted swarm state: %s", exc)

    def _persist_state(self) -> None:
        try:
            payload = {
                "paper_ticks": self._paper_ticks,
                "mode": self._mode.value,
                "state": self._state.value,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            SWARM_STATE_PATH.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        except Exception as exc:
            logger.warning("Failed to persist swarm state: %s", exc)

    async def _redis_pubsub_listener(self) -> None:
        if not self._redis:
            return
        events_channel = f"{self._redis_namespace}:events"
        mem_channel = f"{self._redis_namespace}:mem_updates"
        consecutive_errors = 0
        while self._running:
            pubsub = None
            try:
                pubsub = self._redis.pubsub()
                await pubsub.subscribe(events_channel, mem_channel)
                consecutive_errors = 0
                async for message in pubsub.listen():
                    if message["type"] != "message":
                        continue
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
                raise
            except Exception as e:
                consecutive_errors += 1
                sleep_for = min(10.0 * (2 ** (consecutive_errors - 1)), 300.0)
                logger.error(f"Redis Pub/Sub error: {e}")
                logger.warning(f"⚠️ [SWARM REDIS] Backoff: sleeping {sleep_for:.1f}s before reconnect")
                await asyncio.sleep(sleep_for)
            finally:
                if pubsub is not None:
                    with contextlib.suppress(Exception):
                        await pubsub.unsubscribe(events_channel, mem_channel)
                    with contextlib.suppress(Exception):
                        await pubsub.close()

    async def _monitoring_loop(self) -> None:
        consecutive_errors = 0
        while self._running:
            try:
                await asyncio.sleep(60)
                consecutive_errors = 0
                self._safe_check_data_gaps()
                await self._safe_trigger_retrain()
                recent_brier = self._brier_scores[-10:] if self._brier_scores else []
                if recent_brier and np.mean(recent_brier) > self.BRIER_THRESHOLD:
                    await self._trigger_circuit_breaker(
                        TriggerReason.BRIER_EXCEEDED,
                        {"avg_brier": float(np.mean(recent_brier))}
                    )
            except asyncio.CancelledError:
                break
            except Exception as e:
                consecutive_errors += 1
                logger.error(f"Swarm monitoring loop error (consecutive={consecutive_errors}): {e}")
                sleep_for = min(10.0 * (2 ** (consecutive_errors - 1)), 300.0)
                logger.warning(f"⚠️ [SWARM] Backoff: sleeping {sleep_for:.1f}s")
                await asyncio.sleep(sleep_for)

    async def stop_monitoring(self) -> None:
        self._running = False
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

    def _safe_check_data_gaps(self) -> None:
        try:
            self.check_data_gaps()
        except Exception as e:
            logger.error(f"Data gap check failed: {e}")

    async def _safe_trigger_retrain(self) -> None:
        if not self._should_retrain():
            return
        try:
            await self._trigger_retrain()
        except Exception as e:
            logger.error(f"Retrain cycle failed: {e}")

    def get_status(self) -> Dict[str, Any]:
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
        event = {
            "type": event_type,
            "timestamp": time.time(),
            "data": data,
        }
        await self._event_bus.put(event)
        if self._redis:
            try:
                channel = f"{self._redis_namespace}:events"
                await self._redis.publish(channel, json.dumps(event))
            except Exception as e:
                logger.error(f"📡 Redis publish failed: {e}")

    async def subscribe_events(self) -> asyncio.Queue:
        return self._event_bus

    def set_shared_value(self, key: str, value: Any) -> None:
        self._shared_memory[key] = value
        if self._redis:
            try:
                asyncio.create_task(self._redis.set(
                    f"{self._redis_namespace}:mem:{key}",
                    json.dumps(value)
                ))
                asyncio.create_task(self._redis.publish(
                    f"{self._redis_namespace}:mem_updates",
                    json.dumps({"key": key, "value": value})
                ))
            except Exception as e:
                logger.error(f"💾 Redis set/publish failed for {key}: {e}")

    def get_shared_value(self, key: str, default: Any = None) -> Any:
        return self._shared_memory.get(key, default)

    async def get_shared_value_async(self, key: str, default: Any = None) -> Any:
        if key in self._shared_memory:
            return self._shared_memory[key]
        if self._redis:
            try:
                data = await self._redis.get(f"{self._redis_namespace}:mem:{key}")
                if data:
                    val = json.loads(data)
                    self._shared_memory[key] = val
                    return val
            except Exception as e:
                logger.error(f"💾 Redis get failed for {key}: {e}")
        return default


_supervisor_instance: Optional[RufloSwarmSupervisor] = None


def get_swarm_supervisor(mode: str = "PAPER") -> RufloSwarmSupervisor:
    global _supervisor_instance
    if _supervisor_instance is None:
        _supervisor_instance = RufloSwarmSupervisor(mode=mode)
    return _supervisor_instance


async def initialize_swarm_supervisor(
    mode: str = "PAPER",
    retrain_agent: Any = None,
) -> RufloSwarmSupervisor:
    supervisor = get_swarm_supervisor(mode=mode)
    replay_path = os.getenv("SWARM_WARMSTART_REPLAY_PATH", "").strip()
    if replay_path:
        warm_limit = int(os.getenv("SWARM_WARMSTART_MAX_TICKS", str(supervisor.PAPER_TICKS_REQUIRED)))
        supervisor.warm_start_from_replay(replay_path, max_ticks=warm_limit)
    if retrain_agent:
        supervisor.register_agent("retrain", retrain_agent)
    if not supervisor._running:
        await supervisor.start_monitoring()
    else:
        logger.debug("Swarm supervisor already monitoring.")
    return supervisor
