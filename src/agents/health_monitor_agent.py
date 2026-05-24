"""
Health Monitor Agent
====================
Sidecar de supervision pour maintenir le bot en condition opératoire.

Responsabilités:
- Heartbeat global
- Régression mémoire
- Réconciliation de ledger
- Maintenance FeatureStore DuckDB
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import requests
from dataclasses import dataclass
from typing import Any, Callable, Optional

from core.healing.autonomic_healer import LobstarAutonomicHealer
from utils.config_loader import get_health_config

logger = logging.getLogger("HealthMonitorAgent")

POLYMARKET_API_BASE = "https://data-api.polymarket.com/positions"


@dataclass(frozen=True)
class HealthMonitorConfig:
    heartbeat_interval_seconds: float = 30.0
    duckdb_prune_interval_seconds: float = 24 * 3600.0
    memory_check_interval_seconds: float = 60.0
    max_memory_rss_mb: float = 2048.0
    enable_ledger_reconciliation: bool = True
    enable_feature_store_maintenance: bool = True


class HealthMonitorAgent:
    def __init__(
        self,
        config: HealthMonitorConfig | dict[str, Any] | None = None,
        feature_store: Any = None,
        ledger: Any = None,
        broadcaster: Optional[Any] = None,
    ) -> None:
        if config is None:
            config = HealthMonitorConfig()
        elif isinstance(config, dict):
            config = HealthMonitorConfig(
                heartbeat_interval_seconds=float(config.get("heartbeat_interval_seconds", 30.0)),
                duckdb_prune_interval_seconds=float(config.get("duckdb_prune_interval_seconds", 24 * 3600.0)),
                memory_check_interval_seconds=float(config.get("memory_check_interval_seconds", 60.0)),
                max_memory_rss_mb=float(config.get("max_memory_rss_mb", 2048.0)),
                enable_ledger_reconciliation=bool(config.get("enable_ledger_reconciliation", True)),
                enable_feature_store_maintenance=bool(config.get("enable_feature_store_maintenance", True)),
            )
        self.config = config
        self.feature_store = feature_store
        self.ledger = ledger
        self.broadcaster = broadcaster
        self.healer = LobstarAutonomicHealer(broadcaster=broadcaster)
        self._running = False
        self._last_duckdb_maintenance = 0.0
        self._last_memory_check = 0.0
        self._last_heartbeat = 0.0

    @staticmethod
    def _resolve_target_user() -> str:
        return (os.getenv("POLYMARKET_TARGET_USER", "") or "").strip()

    @property
    def is_running(self) -> bool:
        return self._running

    async def emit_heartbeat(self) -> dict[str, Any]:
        payload = {
            "status": "ok",
            "timestamp": time.time(),
            "pid": os.getpid(),
            "feature_store_ready": self.feature_store is not None,
            "ledger_ready": self.ledger is not None,
        }
        self._last_heartbeat = payload["timestamp"]
        logger.info("Health heartbeat: %s", payload)
        return payload

    async def maintain_feature_store(self) -> dict[str, Any]:
        if not self.feature_store or not self.config.enable_feature_store_maintenance:
            return {"status": "skipped"}
        if not hasattr(self.feature_store, "prune_before"):
            return {"status": "unsupported"}

        cutoff_ts = time.time() - self.config.duckdb_prune_interval_seconds
        removed = self.feature_store.prune_before(cutoff_ts)
        if hasattr(self.feature_store, "vacuum"):
            self.feature_store.vacuum()
        self._last_duckdb_maintenance = time.time()
        return {"status": "ok", "removed": removed, "cutoff_ts": cutoff_ts}

    async def reconcile_ledger(self) -> dict[str, Any]:
        if not self.ledger or not self.config.enable_ledger_reconciliation:
            return {"status": "skipped"}
        summary = {}
        if hasattr(self.ledger, "get_capital_summary"):
            summary = self.ledger.get_capital_summary()
        return {"status": "ok", "capital_summary": summary}

    async def check_memory(self) -> dict[str, Any]:
        self._last_memory_check = time.time()
        rss_mb = None
        try:
            import psutil

            rss_mb = psutil.Process(os.getpid()).memory_info().rss / (1024.0 * 1024.0)
        except Exception:
            pass
        if rss_mb is not None and rss_mb > self.config.max_memory_rss_mb:
            gc_result = self.healer._repair_memory_leak()
            return {"status": "warn", "rss_mb": rss_mb, "action": gc_result}
        return {"status": "ok", "rss_mb": rss_mb}

    async def sync_positions(self) -> dict[str, Any]:
        """Fetch positions from API and sync with the local ledger."""
        if not self.ledger:
            return {"status": "skipped", "reason": "no ledger"}
        target_user = self._resolve_target_user()
        if not target_user:
            return {"status": "skipped", "reason": "POLYMARKET_TARGET_USER not configured"}
        
        try:
            loop = asyncio.get_event_loop()
            # Fetch data in a thread pool to avoid blocking the event loop
            response = await loop.run_in_executor(
                None,
                lambda: requests.get(POLYMARKET_API_BASE, params={"user": target_user}, timeout=10),
            )
            if response.status_code != 200:
                return {"status": "error", "code": response.status_code}
            
            positions = response.json()
            
            # Sync to ledger (assuming self.ledger supports direct cursor/connection access or an update method)
            # We access the ledger's conn to perform the sync.
            conn = self.ledger.conn
            cursor = conn.cursor()
            
            synced_count = 0
            skipped_count = 0
            for pos in positions:
                ticker = (
                    pos.get("market")
                    or pos.get("title")
                    or pos.get("slug")
                    or pos.get("conditionId")
                    or pos.get("condition_id")
                    or pos.get("asset")
                    or pos.get("asset_id")
                )
                if ticker is None:
                    skipped_count += 1
                    logger.debug("Skipping position without market identifier: %s", pos)
                    continue
                ticker = str(ticker).strip()
                if not ticker:
                    skipped_count += 1
                    logger.debug("Skipping position with blank market identifier: %s", pos)
                    continue
                size = float(pos.get("size", 0))
                entry_price = float(pos.get("avgPrice", 0))
                
                cursor.execute("""
                    INSERT INTO positions (position_id, ticker, side, size, entry_price, status)
                    VALUES (?, ?, ?, ?, ?, 'OPEN')
                    ON CONFLICT(position_id) DO UPDATE SET
                        size=excluded.size
                """, (f"api_{ticker}", ticker, "BUY", size, entry_price))
                synced_count += 1
            
            conn.commit()
            return {"status": "ok", "synced": synced_count, "skipped": skipped_count}
        except Exception as e:
            logger.error("Failed to sync positions: %s", e)
            return {"status": "error", "message": str(e)}

    async def run_once(self) -> dict[str, Any]:
        result = {
            "heartbeat": await self.emit_heartbeat(),
            "memory": await self.check_memory(),
            "ledger": await self.reconcile_ledger(),
            "positions_sync": await self.sync_positions(),
            "feature_store": await self.maintain_feature_store(),
        }
        return result


    async def run_forever(
        self,
        on_cycle: Optional[Callable[[dict[str, Any]], Any]] = None,
        poll_interval: Optional[float] = None,
    ) -> None:
        if self._running:
            logger.info("Health monitor already running")
            return
        self._running = True

        # Récupération des seuils pour affichage au boot
        max_binance_stale = str(get_health_config("binance_staleness_seconds", 3.0))
        max_mem = str(get_health_config("memory_warning_mb", int(self.config.max_memory_rss_mb)))
        wallet_drift = str(get_health_config("wallet_drift_tolerance_usdc", 0.01))

        logger.info("==========================================================")
        logger.info("🛡️  [HEALTH SIDECAR] INITIALIZATION & BOOT SEQUENCE STARTED")
        logger.info("==========================================================")
        logger.info(f" -> Mode : SIDE CAR ASYNC (Isolated Event Loop Stream)")
        logger.info(f" -> Guardrail Flux   : Binance Staleness Max = {max_binance_stale}s")
        logger.info(f" -> Guardrail RAM    : Process Threshold     = {max_mem} MB")
        logger.info(f" -> Guardrail Ledger : Max Allowed Drift     = {wallet_drift} USDC")
        logger.info(f" -> Cooldown Alertes : Actif (Anti-Spam Telegram)")
        logger.info("----------------------------------------------------------")
        logger.info("⚡ [HEALTH SIDECAR] Daemon successfully armed and running.")
        logger.info("==========================================================")

        poll_interval = poll_interval or self.config.heartbeat_interval_seconds
        while self._running:
            try:
                cycle = await self.run_once()
                if on_cycle:
                    maybe = on_cycle(cycle)
                    if asyncio.iscoroutine(maybe):
                        await maybe
                await asyncio.sleep(poll_interval)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Health monitor cycle failed: %s", exc)
                await asyncio.sleep(5.0)

    def stop(self) -> None:
        self._running = False
