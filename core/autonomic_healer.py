import os
import re
import logging
import asyncio
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger("LOBSTAR_Healer")


class LobstarAutonomicHealer:
    """
    Moteur de Forensic et d'Auto-Correction de niveau industriel.
    Analyse les logs applicatifs en temps réel et déploie des correctifs à chaud.

    Scan des signatures d'erreurs connues et exécution de contre-mesures autonomes
    sans intervention humaine, avec notification en canal Telegram.
    """

    def __init__(
        self,
        log_file_path: str = "logs/pm2-out.log",
        broadcaster: Optional[Any] = None,
    ) -> None:
        """
        Initialise le moteur d'auto-guérison.

        Args:
            log_file_path: Chemin du fichier de log applicatif
            broadcaster: Instance du TelegramChannelBroadcaster pour notifications
        """
        self.log_path = log_file_path
        self.broadcaster = broadcaster

        # Distributed Memory Access
        self._swarm = None
        try:
            from core.swarm_supervisor import get_swarm_supervisor
            self._swarm = get_swarm_supervisor()
        except ImportError:
            logger.warning("SwarmSupervisor not available in Healer, distributed remediation disabled.")

        # Index de la dernière ligne lue pour éviter de re-scanner tout le fichier
        self._last_position = 0

        # Historique des erreurs réparées (pour éviter les boucles infinies)
        self._repaired_incidents: Dict[str, float] = {}
        self._repair_cooldown = 30.0  # Cooldown en secondes entre deux réparations identiques

        # Base de connaissances des pannes connues et de leurs signatures
        self.signatures_erreurs: Dict[str, str] = {
            "ALCHEMY_RPC_TIMEOUT": r"Timeout.*(?:Alchemy|RPC).*Polygon|eth_.*timeout",
            "SQLITE_WAL_LOCKED": r"database is locked|WAL.*corrupt|attempt to write a readonly database",
            "MICROFISH_PARSING_ERROR": r"json\.decoder\.JSONDecodeError.*(?:microfish|web_scraper)",
            "POLYMARKET_CLOB_DISCONNECTION": r"WebSocket.*closed|CLOB.*connection.*lost",
            "MEMORY_LEAK_DETECTION": r"MemoryError|Resource exhausted",
        }

        # Mapping erreur → action de correction
        self.remediation_actions: Dict[str, callable] = {
            "ALCHEMY_RPC_TIMEOUT": self._repair_rpc_timeout,
            "SQLITE_WAL_LOCKED": self._repair_sqlite_wal,
            "MICROFISH_PARSING_ERROR": self._repair_web_scraper,
            "POLYMARKET_CLOB_DISCONNECTION": self._repair_clob_connection,
            "MEMORY_LEAK_DETECTION": self._repair_memory_leak,
        }

    def analyser_nouveaux_logs(self) -> List[str]:
        """
        Scanne uniquement les nouvelles lignes ajoutées au fichier de log.
        Utilise les pointeurs seek/tell pour éviter de relire l'ensemble du fichier.

        Returns:
            Liste des IDs d'erreurs détectées
        """
        if not os.path.exists(self.log_path):
            logger.debug(f"Log file not found: {self.log_path}")
            return []

        alertes_detectees = []

        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                # Déplacement direct au dernier index lu
                f.seek(self._last_position)
                nouvelles_lignes = f.readlines()
                self._last_position = f.tell()

            for ligne in nouvelles_lignes:
                # Filtrer sur les lignes d'erreur
                if "ERROR" in ligne or "CRITICAL" in ligne or "FATAL" in ligne:
                    for alerte_id, pattern in self.signatures_erreurs.items():
                        if re.search(pattern, ligne, re.IGNORECASE):
                            if alerte_id not in alertes_detectees:
                                alertes_detectees.append(alerte_id)
                                logger.warning(f"🚨 [FORENSIC] Erreur détectée: {alerte_id}")
                                logger.debug(f"  Ligne: {ligne.strip()[:100]}")

        except Exception as e:
            logger.error(f"Erreur lors de la lecture des logs: {e}")

        return alertes_detectees

    def _should_attempt_repair(self, erreur_id: str) -> bool:
        """
        Vérifie si on doit tenter la réparation (cooldown check).

        Args:
            erreur_id: Identifiant de l'erreur

        Returns:
            True si on peut tenter la réparation, False si en cooldown
        """
        now = datetime.now().timestamp()
        last_repair = self._repaired_incidents.get(erreur_id, 0.0)

        if now - last_repair < self._repair_cooldown:
            logger.debug(f"⏳ [COOLDOWN] {erreur_id} en cooldown (reste {self._repair_cooldown - (now - last_repair):.1f}s)")
            return False

        return True

    def _mark_repair_attempted(self, erreur_id: str) -> None:
        """Enregistre le moment de la tentative de réparation."""
        self._repaired_incidents[erreur_id] = datetime.now().timestamp()

    # ─────────────────────────────────────────────────────────────────
    # REMEDIATION ACTIONS (Contre-mesures autonomes)
    # ─────────────────────────────────────────────────────────────────

    def _repair_rpc_timeout(self) -> Dict[str, Any]:
        """
        Remède: Basculer sur le nœud RPC de secours (QuickNode) directement en RAM.
        """
        try:
            backup_rpc = os.getenv("BACKUP_QUICKNODE_RPC_URL", "")
            if backup_rpc:
                os.environ["POLYGON_RPC_URL"] = backup_rpc
                if self._swarm:
                    asyncio.create_task(self._swarm.publish_event("INFRA_RPC_SWITCH", {"new_rpc": backup_rpc}))
                logger.info(f"✅ [REMEDIATION] RPC basculé vers: {backup_rpc[:50]}...")
                return {
                    "statut": "REPAIRED",
                    "action": "SWITCHED_TO_BACKUP_RPC_NODE",
                    "details": f"Basculement vers QuickNode"
                }
            else:
                logger.warning("❌ BACKUP_QUICKNODE_RPC_URL non configuré")
                return {
                    "statut": "FAILED",
                    "action": "NO_BACKUP_RPC_AVAILABLE",
                    "details": "Variable BACKUP_QUICKNODE_RPC_URL manquante"
                }
        except Exception as e:
            logger.error(f"❌ Erreur RPC repair: {e}")
            return {"statut": "FAILED", "action": "RPC_REPAIR_ERROR", "details": str(e)}

    def _repair_sqlite_wal(self) -> Dict[str, Any]:
        """
        Remède: Forcer la libération des verrous SQLite WAL et des fichiers de partage.
        """
        try:
            db_dir = "user_data/data"
            files_to_remove = [
                os.path.join(db_dir, "ledger.db-shm"),
                os.path.join(db_dir, "ledger.db-wal"),
            ]

            removed_count = 0
            for file_path in files_to_remove:
                if os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                        removed_count += 1
                        logger.info(f"✅ Supprimé: {file_path}")
                    except Exception as e:
                        logger.warning(f"Impossible de supprimer {file_path}: {e}")

            if removed_count > 0:
                if self._swarm:
                    asyncio.create_task(self._swarm.publish_event("DB_WAL_FLUSHED", {"files_removed": removed_count}))
                return {
                    "statut": "REPAIRED",
                    "action": "FLUSHED_WAL_SHARED_MEMORY",
                    "details": f"{removed_count} fichier(s) SQLite WAL/SHM supprimé(s)"
                }
            else:
                return {
                    "statut": "REPAIRED",
                    "action": "WAL_ALREADY_CLEAN",
                    "details": "Pas de fichiers WAL/SHM trouvés"
                }
        except Exception as e:
            logger.error(f"❌ Erreur SQLite WAL repair: {e}")
            return {"statut": "FAILED", "action": "SQLITE_REPAIR_ERROR", "details": str(e)}

    def _repair_web_scraper(self) -> Dict[str, Any]:
        """
        Remède: Réinitialiser le buffer du scraper web et nettoyer les états de session.
        """
        try:
            # Incrémenter un compteur de réinitialisation dans l'env
            reset_count = int(os.getenv("SCRAPER_RESETS", "0")) + 1
            os.environ.setdefault("SCRAPER_RESETS", str(reset_count))
            os.environ.setdefault("MICROFISH_BUFFER_FLUSHED", "true")

            if self._swarm:
                self._swarm.set_shared_value("scraper:resets", reset_count)
                asyncio.create_task(self._swarm.publish_event("SCRAPER_BUFFER_RESET", {"reset_count": reset_count}))

            logger.info(f"✅ [REMEDIATION] Web scraper buffer réinitialisé (réinitialisation #{reset_count})")
            return {
                "statut": "REPAIRED",
                "action": "RESET_WEB_SCRAPER_BUFFER",
                "details": f"Réinitialisation #{reset_count} du buffer Microfish"
            }
        except Exception as e:
            logger.error(f"❌ Erreur web scraper repair: {e}")
            return {"statut": "FAILED", "action": "SCRAPER_REPAIR_ERROR", "details": str(e)}

    def _repair_clob_connection(self) -> Dict[str, Any]:
        """
        Remède: Signaler au gestionnaire de connexion de réinitialiser la connexion WebSocket CLOB.
        """
        try:
            # Forcer un drapeau de réinitialisation
            os.environ.setdefault("FORCE_CLOB_RECONNECT", "true")
            if self._swarm:
                asyncio.create_task(self._swarm.publish_event("CLOB_FORCE_RECONNECT", {}))
            logger.info("✅ [REMEDIATION] Reconnexion CLOB demandée")
            return {
                "statut": "REPAIRED",
                "action": "FORCE_CLOB_RECONNECT",
                "details": "Flag de reconnexion WebSocket CLOB activé"
            }
        except Exception as e:
            logger.error(f"❌ Erreur CLOB reconnect: {e}")
            return {"statut": "FAILED", "action": "CLOB_RECONNECT_ERROR", "details": str(e)}

    def _repair_memory_leak(self) -> Dict[str, Any]:
        """
        Remède: Signaler le besoin d'un garbage collection ou d'un redémarrage gracieux.
        """
        try:
            import gc
            gc.collect()
            if self._swarm:
                asyncio.create_task(self._swarm.publish_event("INFRA_GC_COLLECT", {}))
            logger.info("✅ [REMEDIATION] Garbage collection forcé")
            return {
                "statut": "REPAIRED",
                "action": "FORCED_GARBAGE_COLLECTION",
                "details": "Nettoyage mémoire en profondeur exécuté"
            }
        except Exception as e:
            logger.error(f"❌ Erreur memory cleanup: {e}")
            return {"statut": "FAILED", "action": "MEMORY_CLEANUP_ERROR", "details": str(e)}

    # ─────────────────────────────────────────────────────────────────
    # DISPATCH & BROADCAST
    # ─────────────────────────────────────────────────────────────────

    async def deployer_correctif_autonome(self, erreur_id: str) -> Dict[str, Any]:
        """
        Déclenche la contre-mesure corrective autonome appropriée.

        Args:
            erreur_id: Identifiant de l'erreur à corriger

        Returns:
            Dictionnaire avec statut et détails de la réparation
        """
        # Vérifier le cooldown
        if not self._should_attempt_repair(erreur_id):
            return {"statut": "SKIPPED", "raison": "En cooldown"}

        self._mark_repair_attempted(erreur_id)
        logger.warning(f"🔧 [SELF-HEALING] Déploiement du correctif pour: [{erreur_id}]")

        # Récupérer la fonction de remède
        if erreur_id not in self.remediation_actions:
            logger.warning(f"⚠️ Pas de remède connu pour: {erreur_id}")
            return {
                "statut": "UNKNOWN_ERROR",
                "action": "FORWARD_TO_RUFLO_COGNITION",
                "details": f"Aucun remède automatique pour {erreur_id}"
            }

        # Exécuter le remède
        try:
            remediation_func = self.remediation_actions[erreur_id]
            resultat = remediation_func()

            # Broadcaster la notification
            if self.broadcaster and resultat.get("statut") in ["REPAIRED", "PARTIALLY_REPAIRED"]:
                await self._broadcaster_notification(erreur_id, resultat)

            return resultat

        except Exception as e:
            logger.error(f"❌ [REMEDIATION CRASH] {erreur_id}: {e}")
            return {
                "statut": "FAILED",
                "action": "REMEDIATION_EXCEPTION",
                "details": str(e)
            }

    async def _broadcaster_notification(self, erreur_id: str, resultat: Dict[str, Any]) -> bool:
        """
        Envoie un rapport de réparation au canal Telegram (Markdown V1).

        Args:
            erreur_id: ID de l'incident
            resultat: Résultat de la réparation

        Returns:
            True si notification envoyée, False sinon
        """
        if not self.broadcaster:
            logger.debug("Broadcaster non disponible, pas de notification")
            return False

        try:
            esc = getattr(self.broadcaster, "_formatter", None)
            if esc and hasattr(esc, "escape_markdown_v2"):
                esc_func = esc.escape_markdown_v2
            else:
                esc_func = lambda x: str(x)

            action_esc = esc_func(resultat.get('action', 'N/A'))
            details_esc = esc_func(resultat.get('details', 'N/A'))
            erreur_id_esc = esc_func(erreur_id)

            message = (
                f"• *Incident* : `{erreur_id_esc}`\n"
                f"• *Severity* : `CRITICAL`\n"
                f"• *Action* : `{action_esc}`\n"
                f"• *Details* : `{details_esc}`"
            )

            # Utiliser la méthode diffuser_alerte_risque_au_canal
            success = await self.broadcaster.diffuser_alerte_risque_au_canal({
                "title": f"Infrastructure Self-Healing",
                "message": message,
                "severity": "warning" if resultat.get("statut") == "PARTIALLY_REPAIRED" else "info"
            }, escape_body=False)

            if success:
                logger.info(f"✅ [BROADCAST] Notification de réparation envoyée pour {erreur_id}")

            return success

        except Exception as e:
            logger.error(f"❌ Erreur lors de la notification broadcaster: {e}")
            return False

    async def scan_et_guerir_continu(self, interval_seconds: float = 2.0) -> None:
        """
        Boucle infinie de scan des logs et auto-guérison.
        À intégrer dans le QuantumRunner comme une tâche background.

        Args:
            interval_seconds: Intervalle de scan en secondes
        """
        logger.info(f"🏥 [AUTONOMIC HEALER] Démarrage du scan continu (interval: {interval_seconds}s)")

        try:
            while True:
                try:
                    # Analyser les nouveaux logs
                    erreurs = self.analyser_nouveaux_logs()

                    # Déployer les correctifs
                    for erreur_id in erreurs:
                        resultat = await self.deployer_correctif_autonome(erreur_id)
                        logger.info(f"🔧 [{erreur_id}] Résultat: {resultat.get('statut')}")

                    # Attendre avant le prochain scan
                    await asyncio.sleep(interval_seconds)

                except asyncio.CancelledError:
                    logger.info("💤 [AUTONOMIC HEALER] Scan continu annulé")
                    break
                except Exception as e:
                    logger.error(f"❌ [AUTONOMIC HEALER] Erreur dans la boucle de scan: {e}")
                    await asyncio.sleep(interval_seconds)

        except Exception as e:
            logger.error(f"❌ [AUTONOMIC HEALER] Erreur critique: {e}")
