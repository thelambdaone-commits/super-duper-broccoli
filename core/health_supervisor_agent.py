from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("LOBSTAR_HealthSupervisor")

try:  # pragma: no cover - optional dependency
    import psutil as _psutil
except Exception:  # pragma: no cover - optional dependency missing
    _psutil = None


@dataclass(slots=True)
class HealthSupervisorConfig:
    staleness_threshold_seconds: float = 30.0
    memory_warning_mb: float = 1024.0
    memory_critical_mb: float = 1536.0
    wallet_reconciliation_interval_seconds: float = 3600.0
    maintenance_interval_seconds: float = 86400.0
    check_interval_seconds: float = 5.0
    wallet_drift_tolerance_usd: float = 1.0
    disk_usage_warning_bytes: int = 5_000_000_000
    disk_usage_critical_bytes: int = 8_000_000_000
    alert_cooldown_seconds: float = 300.0
    maintenance_tables: tuple[str, ...] = (
        "market_microstructure",
        "features_computed",
        "signals_ingested",
        "decisions_log",
        "web_events_raw",
    )
    stream_tables: tuple[str, ...] = ("market_microstructure", "web_events_raw")


@dataclass(slots=True)
class HealthSupervisorState:
    last_wallet_reconciliation: float = 0.0
    last_maintenance: float = 0.0
    last_alert_at: dict[str, float] = field(default_factory=dict)


def _read_process_rss_mb() -> float:
    if _psutil is not None:
        return float(_psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024))

    try:
        with open("/proc/self/status", "r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    parts = re.findall(r"\d+", line)
                    if parts:
                        return float(parts[0]) / 1024.0
    except Exception:
        pass

    return 0.0


class HealthSupervisorAgent:
    """Sidecar-like runtime health supervisor.

    Runs alongside the trading loop and keeps operational checks isolated from
    the strategy path.
    """

    def __init__(
        self,
        feature_store: Any,
        ledger: Any,
        wallet_manager: Any,
        data_archiver: Any,
        broadcaster: Any = None,
        secrets: Optional[dict[str, str]] = None,
        config: Optional[HealthSupervisorConfig] = None,
    ) -> None:
        self.feature_store = feature_store
        self.ledger = ledger
        self.wallet_manager = wallet_manager
        self.data_archiver = data_archiver
        self.broadcaster = broadcaster
        self.secrets = secrets or {}
        self.config = config or HealthSupervisorConfig()
        self.state = HealthSupervisorState()
        self._is_running = False

    async def start(self) -> None:
        self._is_running = True
        logger.info("🏥 [HEALTH SUPERVISOR] Started")
        while self._is_running:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Health supervisor iteration failed: %s", exc)
            await asyncio.sleep(self.config.check_interval_seconds)

    def stop(self) -> None:
        self._is_running = False
        logger.info("🏥 [HEALTH SUPERVISOR] Stop requested")

    async def run_once(self, now: Optional[datetime] = None) -> list[dict[str, Any]]:
        checks: list[dict[str, Any]] = []
        ts = (now or datetime.now(timezone.utc)).timestamp()

        staleness = await self.check_stream_staleness(ts)
        if staleness:
            checks.append(staleness)

        memory = await self.check_memory_usage()
        if memory:
            checks.append(memory)

        if ts - self.state.last_wallet_reconciliation >= self.config.wallet_reconciliation_interval_seconds:
            reconciliation = await self.reconcile_wallet_balances(ts)
            if reconciliation:
                checks.append(reconciliation)
            self.state.last_wallet_reconciliation = ts

        if ts - self.state.last_maintenance >= self.config.maintenance_interval_seconds:
            maintenance = await self.run_maintenance_cycle(ts)
            if maintenance:
                checks.append(maintenance)
            self.state.last_maintenance = ts

        return checks

    async def check_stream_staleness(self, now_ts: Optional[float] = None) -> Optional[dict[str, Any]]:
        now_ts = time.time() if now_ts is None else float(now_ts)
        latest_ts = self._latest_stream_timestamp()

        if latest_ts is None:
            await self._notify_once("stream_staleness", "Health check alert. No live stream data found in FeatureStore.")
            return {
                "check": "stream_staleness",
                "status": "CRITICAL",
                "reason": "no_stream_data",
            }

        age = now_ts - latest_ts
        if age > self.config.staleness_threshold_seconds:
            await self._notify_once(
                "stream_staleness",
                f"Health check alert. Live data stale for {age:.1f} seconds. "
                f"Threshold is {self.config.staleness_threshold_seconds:.1f} seconds.",
            )
            return {
                "check": "stream_staleness",
                "status": "CRITICAL",
                "age_seconds": age,
                "threshold_seconds": self.config.staleness_threshold_seconds,
            }

        return {
            "check": "stream_staleness",
            "status": "OK",
            "age_seconds": age,
            "threshold_seconds": self.config.staleness_threshold_seconds,
        }

    async def check_memory_usage(self) -> Optional[dict[str, Any]]:
        rss_mb = _read_process_rss_mb()
        status = "OK"
        if rss_mb >= self.config.memory_critical_mb:
            status = "CRITICAL"
        elif rss_mb >= self.config.memory_warning_mb:
            status = "WARNING"

        if status != "OK":
            logger.warning(
                "Health supervisor memory check %s: rss=%.1fMB warning=%.1fMB critical=%.1fMB",
                status,
                rss_mb,
                self.config.memory_warning_mb,
                self.config.memory_critical_mb,
            )
            if status == "CRITICAL":
                await self._notify_once(
                    "memory_usage",
                    "Health check alert. Memory usage exceeded the critical threshold. "
                    f"RSS {rss_mb:.1f} MB.",
                )

        return {
            "check": "memory_usage",
            "status": status,
            "rss_mb": rss_mb,
            "warning_mb": self.config.memory_warning_mb,
            "critical_mb": self.config.memory_critical_mb,
        }

    async def reconcile_wallet_balances(self, now_ts: Optional[float] = None) -> Optional[dict[str, Any]]:
        wallet_address = self._resolve_wallet_address()
        if not wallet_address:
            return {
                "check": "wallet_reconciliation",
                "status": "SKIPPED",
                "reason": "no_wallet_address",
            }

        proxy_address = self._resolve_proxy_address()
        try:
            balances = await self.wallet_manager.recuperer_soldes_on_chain(wallet_address, proxy_address=proxy_address)
        except Exception as exc:
            await self._notify_once("wallet_reconciliation", f"Health check alert. Wallet reconciliation failed. {exc}")
            return {
                "check": "wallet_reconciliation",
                "status": "CRITICAL",
                "reason": "wallet_fetch_failed",
                "error": str(exc),
            }

        capital_summary = self.ledger.get_capital_summary() if self.ledger else {}
        ledger_available = float(capital_summary.get("available_capital", 0.0) or 0.0)
        ledger_total = float(capital_summary.get("total_capital", ledger_available) or ledger_available)
        onchain_usdc = float(balances.get("usdc_balance", 0.0) or 0.0)
        drift = abs(onchain_usdc - ledger_available)
        status = "OK" if drift <= self.config.wallet_drift_tolerance_usd else "WARNING"

        if status != "OK":
            await self._notify_once(
                "wallet_reconciliation",
                "Health check alert. Wallet balance drift detected. "
                f"On-chain USDC {onchain_usdc:.2f} vs ledger available {ledger_available:.2f}. "
                f"Drift {drift:.2f}. Auto-syncing ledger capital..."
            )
            # Perform actual sync to adapt strategy
            if onchain_usdc > 0:
                self.ledger.sync_capital(onchain_usdc)
                if hasattr(self.ledger, "risk") and self.ledger.risk:
                    self.ledger.risk.rehydrate_from_ledger(self.ledger)

        return {
            "check": "wallet_reconciliation",
            "status": status,
            "wallet_address": wallet_address,
            "proxy_address": proxy_address,
            "onchain_usdc": onchain_usdc,
            "ledger_available_capital": ledger_available,
            "ledger_total_capital": ledger_total,
            "drift_usd": drift,
            "tolerance_usd": self.config.wallet_drift_tolerance_usd,
        }

    async def run_maintenance_cycle(self, now_ts: Optional[float] = None) -> Optional[dict[str, Any]]:
        now_ts = time.time() if now_ts is None else float(now_ts)
        try:
            result = await asyncio.to_thread(self.data_archiver.run_maintenance_cycle)
        except Exception as exc:
            await self._notify(f"Health check alert. Maintenance cycle failed. {exc}")
            return {
                "check": "maintenance",
                "status": "CRITICAL",
                "reason": "maintenance_failed",
                "error": str(exc),
            }

        disk_usage = result.get("disk_usage", {})
        total_disk = sum(int(v) for v in disk_usage.values() if isinstance(v, (int, float)))
        status = "OK"
        if total_disk >= self.config.disk_usage_critical_bytes:
            status = "CRITICAL"
        elif total_disk >= self.config.disk_usage_warning_bytes:
            status = "WARNING"

        if status != "OK":
            await self._notify_once(
                "disk_usage",
                "Health check alert. Disk usage is elevated. "
                f"Total {total_disk} bytes."
            )

        payload = {
            "check": "maintenance",
            "status": status,
            "timestamp": now_ts,
            "disk_usage_bytes": total_disk,
            "result": result,
        }
        logger.info("Health supervisor maintenance cycle completed: %s", payload["status"])
        return payload

    async def _notify(self, message: str) -> None:
        if not self.broadcaster:
            logger.warning(message)
            return

        try:
            sender = getattr(self.broadcaster, "diffuser_message_au_canal", None)
            if sender:
                await sender(message)
                return
            sender = getattr(self.broadcaster, "send", None)
            if sender:
                maybe = sender(message)
                if asyncio.iscoroutine(maybe):
                    await maybe
                return
        except Exception as exc:
            logger.warning("Health supervisor alert dispatch failed: %s", exc)

    async def _notify_once(self, key: str, message: str) -> None:
        now = time.time()
        last = self.state.last_alert_at.get(key, 0.0)
        if now - last < self.config.alert_cooldown_seconds:
            return
        self.state.last_alert_at[key] = now
        await self._notify(message)

    def _latest_stream_timestamp(self) -> Optional[float]:
        latest = None
        for table in self.config.stream_tables:
            try:
                ts = self.feature_store.get_latest_timestamp(table)
            except Exception:
                ts = None
            if ts is not None:
                latest = ts if latest is None else max(latest, ts)
        return latest

    def _resolve_wallet_address(self) -> str:
        for key in ("POLYMARKET_WALLET_ADDRESS", "WALLET_ADDRESS", "address"):
            value = self.secrets.get(key) or os.getenv(key, "")
            if value:
                return str(value)
        return ""

    def _resolve_proxy_address(self) -> str:
        for key in ("POLYMARKET_PROXY_WALLET_ADDRESS", "PROXY_WALLET_ADDRESS", "proxy_wallet"):
            value = self.secrets.get(key) or os.getenv(key, "")
            if value:
                return str(value)
        return ""
