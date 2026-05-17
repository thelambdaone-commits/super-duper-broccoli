import asyncio
import time
import logging
from typing import Dict, Any, List, Callable, Coroutine

logger = logging.getLogger("LOBSTAR_QuantumRunner")


class QuantumJob:
    """
    Structure représentant une tâche planifiée au sein du Runner.
    """
    def __init__(self, name: str, callback: Callable[[], Coroutine[Any, Any, None]], interval_sec: float) -> None:
        self.name = name
        self.callback = callback
        self.interval = interval_sec
        self.last_run = 0.0


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

    def enregistrer_job(self, name: str, callback: Callable[[], Coroutine[Any, Any, None]], interval_sec: float) -> None:
        """Ajoute une tâche récurrente dans le calendrier de la montre interne."""
        self.jobs.append(QuantumJob(name, callback, interval_sec))
        logger.info(f"⏱️ [MONTRE INTERNE] Job enregistré : [{name}] programmé toutes les {interval_sec}s.")

    async def start(self) -> None:
        """Démarre le Runner Bot et active la montre interne."""
        self._is_running = True
        logger.info("🚀 [RUNNER BOT] Démarrage du moteur d'exécution et de la montre interne...")
        
        while self._is_running:
            temps_actuel = time.monotonic()
            
            # Parcours des tâches enregistrées pour vérification de l'échéance
            tasks = []
            for job in self.jobs:
                if temps_actuel - job.last_run >= job.interval:
                    # L'échéance est atteinte, on prépare l'exécution asynchrone
                    job.last_run = temps_actuel
                    tasks.append(self._executer_job_safely(job))
            
            # Lancement simultané des tâches prêtes sans bloquer la montre
            if tasks:
                asyncio.create_task(self._run_concurrent_batch(tasks))
                
            # Battement de cœur de la montre interne (10ms)
            await asyncio.sleep(self.montre_interne_tick_rate)

    async def _executer_job_safely(self, job: QuantumJob) -> None:
        """Exécute un job individuel en l'encapsulant pour éviter les crashs globaux."""
        start_profiling = time.perf_counter()
        try:
            await job.callback()
            duration = (time.perf_counter() - start_profiling) * 1000
            if duration > (job.interval * 1000):
                logger.warning(f"⚠️ [RUNNER] Job [{job.name}] a dépassé son allocation temporelle : {duration:.2f}ms")
        except Exception as e:
            logger.error(f"❌ [RUNNER CRASH DETECTED] Échec d'exécution sur le job [{job.name}] : {e}")

    async def _run_concurrent_batch(self, tasks: List[Coroutine[Any, Any, None]]) -> None:
        """Exécute le lot de tâches prêtes en parallèle."""
        await asyncio.gather(*tasks, return_exceptions=True)

    def stop(self) -> None:
        """Arrête proprement le Runner Bot."""
        self._is_running = False
        logger.info("💤 [RUNNER BOT] Arrêt de la montre interne demandé.")
