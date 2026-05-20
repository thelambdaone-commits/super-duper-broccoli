import asyncio
import logging
import os
from typing import Any, Dict, Optional

from utils.telegram.formatter import TelegramMessageFormatter
from utils.telegram.transport import TelegramTransportClient

logger = logging.getLogger("LOBSTAR_Broadcaster")


class TelegramChannelBroadcaster:
    """
    Module d'émission ciblant les canaux Telegram d'Alpha institutionnels.
    Formatage strict en Markdown V1.
    Isole les alertes de trading (canal) des commandes de gestion (privé).
    """

    def __init__(self, bot_instance: Any = None, formatter: Optional[TelegramMessageFormatter] = None, transport: Optional[TelegramTransportClient] = None) -> None:
        """
        Initialise le broadcaster avec l'instance du bot Telegram.

        Args:
            bot_instance: Instance du bot Telegram (python-telegram-bot)
        """
        self.bot = bot_instance
        self.formatter = formatter or TelegramMessageFormatter()
        # Extraction du canal cible (ex: "@LobstarAlphaSignals" ou "-100123456789")
        self.channel_id = os.getenv("TELEGRAM_BROADCASTER_CHANNEL_ID") or os.getenv("TELEGRAM_CHANNEL_ID")
        self.transport = transport

        if not self.channel_id:
            logger.warning("⚠️ [BROADCASTER] TELEGRAM_CHANNEL_ID non configuré. Les signaux ne seront pas diffusés.")

    async def diffuser_signal_au_canal(self, data: Dict[str, Any]) -> bool:
        """
        Pousse le signal prédictif validé directement dans le canal d'abonnés.

        Args:
            data: Dictionnaire contenant :
                - ticker: Symbol du marché
                - side: "YES"/"BUY" ou "NO"/"SELL"
                - regime: Régime HMM actuel
                - p_market: Probabilité implicite du marché
                - p_real: Probabilité calibrée de l'IA
                - edge: Edge absolu en pourcentage
                - kelly: Fraction de Kelly recommandée

        Returns:
            bool: True si l'envoi a réussi, False sinon
        """
        if not self.channel_id:
            logger.error("❌ [BROADCAST ERROR] Aucun TELEGRAM_CHANNEL_ID configuré en RAM.")
            return False

        try:
            message = self.formatter.format_signal(data)
            await self._send(message)
            logger.info(
                f"📡 [BROADCAST SUCCESS] Signal {data.get('ticker')} "
                f"poussé vers le canal {self.channel_id}"
            )
            return True

        except Exception as e:
            logger.error(f"❌ [BROADCAST CRASH] Échec de l'envoi au canal : {e}")
            return False

    async def diffuser_alerte_risque_au_canal(self, alert_data: Dict[str, Any]) -> bool:
        """
        Envoie une alerte de risque au canal (par ex. Circuit Breaker activé).

        Args:
            alert_data: Dictionnaire contenant :
                - title: Titre de l'alerte
                - message: Corps du message
                - severity: "warning", "critical", "info"

        Returns:
            bool: True si l'envoi a réussi, False sinon
        """
        if not self.channel_id:
            logger.warning("⚠️ [BROADCAST] Canal non configuré ou bot indisponible.")
            return False

        try:
            severity = str(alert_data.get("severity", "info")).upper()
            message = self.formatter.format_risk_alert(alert_data)
            await self._send(message)
            logger.info(f"📡 [ALERT BROADCAST] {severity} alert sent to channel.")
            return True

        except Exception as e:
            logger.error(f"❌ [ALERT BROADCAST FAILED] {e}")
            return False

    async def diffuser_message_au_canal(self, text: str) -> bool:
        if not self.channel_id:
            logger.warning("⚠️ [BROADCAST] Canal non configuré ou bot indisponible.")
            return False
        try:
            await self._send(text)
            logger.info("📡 [BROADCAST SUCCESS] Message diffusé vers le canal %s", self.channel_id)
            return True
        except Exception as e:
            logger.error(f"❌ [BROADCAST FAILED] {e}")
            return False

    async def _send(self, text: str) -> bool:
        if self.transport:
            return await asyncio.to_thread(self.transport.send_raw_message, text)
        if self.bot:
            await self.bot.send_message(chat_id=self.channel_id, text=text, parse_mode="MarkdownV2")
            return True
        return False
