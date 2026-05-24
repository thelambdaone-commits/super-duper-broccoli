import asyncio
import time
import logging
from dataclasses import dataclass
from typing import Any, List, Callable, Coroutine

from core.resource_governor import get_resource_governor

logger = logging.getLogger("LOBSTAR_QuantumRunner")


@dataclass
class QuantumJobStats:
    run_count: int = 0
    success_count: int = 0
    error_count: int = 0
    skip_count: int = 0
    total_duration_ms: float = 0.0
    last_duration_ms: float = 0.0
    max_duration_ms: float = 0.0

    @property
    def avg_duration_ms(self) -> float:
        return self.total_duration_ms / self.success_count if self.success_count else 0.0


class QuantumJob:
    """
    Structure représentant une tâche planifiée au sein du Runner.
    """
    def __init__(
        self,
        name: str,
        callback: Callable[[], Coroutine[Any, Any, None]],
        interval_sec: float,
        resource_profile: str = "normal",
    ) -> None:
        self.name = name
        self.callback = callback
        self.interval = interval_sec
        self.base_interval = interval_sec
        self.resource_profile = resource_profile
        self.last_run = 0.0
        self.stats = QuantumJobStats()


class LobstarQuantumRunner:
    """
    Le Runner Bot & Montre Interne de grade institutionnel.
    Cadence, supervise et exécute les tâches de l'essaim multi-agents
    sans jamais bloquer la boucle d'événements asynchrone.
    """
    def __init__(self) -> None:
        self.jobs: List[QuantumJob] = []
        self._is_running = False
        self.montre_interne_tick_rate = 0.01  # Résolution de la montre : 10 millisecondes
        self.resource_governor = get_resource_governor()
        self._last_stats_log_at = 0.0
        self._stats_log_interval_sec = 300.0
        self._stats_snapshot: dict[str, dict[str, float | int | str]] = {}

    def register_job(
        self,
        name: str,
        callback: Callable[[], Coroutine[Any, Any, None]],
        interval_sec: float,
        resource_profile: str = "normal",
    ) -> None:
        """Ajoute une tâche récurrente dans le calendrier de la montre interne."""
        self.jobs.append(QuantumJob(name, callback, interval_sec, resource_profile=resource_profile))
        logger.info(
            "⏱️ [MONTRE INTERNE] Job enregistré : [%s] toutes les %ss (profile=%s).",
            name,
            interval_sec,
            resource_profile,
        )

    def enregistrer_job(
        self,
        name: str,
        callback: Callable[[], Coroutine[Any, Any, None]],
        interval_sec: float,
        resource_profile: str = "normal",
    ) -> None:
        self.register_job(name, callback, interval_sec, resource_profile=resource_profile)

    async def start(self) -> None:
        """Démarre le Runner Bot et active la montre interne."""
        self._is_running = True
        logger.info("🚀 [RUNNER BOT] Démarrage du moteur d'exécution et de la montre interne...")

        while self._is_running:
            temps_actuel = time.monotonic()
            self.resource_governor.sample_if_due()

            # Parcours des tâches enregistrées pour vérification de l'échéance
            tasks = []
            for job in self.jobs:
                current_interval = job.base_interval * self.resource_governor.interval_multiplier(job.resource_profile)
                job.interval = current_interval
                if self.resource_governor.should_skip_job(job.resource_profile):
                    job.stats.skip_count += 1
                    continue
                if temps_actuel - job.last_run >= current_interval:
                    # L'échéance est atteinte, on prépare l'exécution asynchrone
                    job.last_run = temps_actuel
                    tasks.append(self._executer_job_safely(job))

            # Lancement simultané des tâches prêtes sans bloquer la montre
            if tasks:
                asyncio.create_task(self._run_concurrent_batch(tasks))

            self._log_stats_if_due(temps_actuel)

            # Battement de cœur de la montre interne (10ms)
            await asyncio.sleep(self.montre_interne_tick_rate)

    async def _executer_job_safely(self, job: QuantumJob) -> None:
        """Exécute un job individuel en l'encapsulant pour éviter les crashs globaux."""
        start_profiling = time.perf_counter()
        job.stats.run_count += 1
        try:
            if job.resource_profile == "heavy":
                logger.info("🏋️ [RUNNER] Heavy job in progress: %s", job.name)
            await job.callback()
            duration = (time.perf_counter() - start_profiling) * 1000
            job.stats.success_count += 1
            job.stats.total_duration_ms += duration
            job.stats.last_duration_ms = duration
            job.stats.max_duration_ms = max(job.stats.max_duration_ms, duration)
            if duration > (job.interval * 1000):
                logger.warning(f"⚠️ [RUNNER] Job [{job.name}] a dépassé son allocation temporelle : {duration:.2f}ms")
        except Exception as e:
            job.stats.error_count += 1
            logger.error(f"❌ [RUNNER CRASH DETECTED] Échec d'exécution sur le job [{job.name}] : {e}")

    async def _run_concurrent_batch(self, tasks: List[Coroutine[Any, Any, None]]) -> None:
        """Exécute le lot de tâches prêtes en parallèle."""
        await asyncio.gather(*tasks, return_exceptions=True)

    def get_job_stats(self) -> dict[str, dict[str, float | int | str]]:
        snapshot: dict[str, dict[str, float | int | str]] = {}
        for job in self.jobs:
            snapshot[job.name] = {
                "resource_profile": job.resource_profile,
                "interval_sec": round(job.interval, 3),
                "base_interval_sec": round(job.base_interval, 3),
                "run_count": job.stats.run_count,
                "success_count": job.stats.success_count,
                "error_count": job.stats.error_count,
                "skip_count": job.stats.skip_count,
                "last_duration_ms": round(job.stats.last_duration_ms, 3),
                "avg_duration_ms": round(job.stats.avg_duration_ms, 3),
                "max_duration_ms": round(job.stats.max_duration_ms, 3),
            }
        self._stats_snapshot = snapshot
        return snapshot

    def _log_stats_if_due(self, now: float) -> None:
        if now - self._last_stats_log_at < self._stats_log_interval_sec:
            return
        self._last_stats_log_at = now
        stats = self.get_job_stats()
        if stats:
            logger.info("📊 [RUNNER] Job stats snapshot: %s", stats)

    def stop(self) -> None:
        """Arrête proprement le Runner Bot."""
        self._is_running = False
        logger.info("💤 [RUNNER BOT] Arrêt de la montre interne demandé.")
