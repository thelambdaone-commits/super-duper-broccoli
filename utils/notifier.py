import asyncio
import logging
import os
import socket
import httpx
from typing import Optional

logger = logging.getLogger("Notifier")


def _is_transient_network_error(exc: Exception) -> bool:
    transient_types = (
        socket.gaierror,
        httpx.ConnectError,
        httpx.ConnectTimeout,
        httpx.ReadTimeout,
        httpx.RemoteProtocolError,
        httpx.NetworkError,
        httpx.PoolTimeout,
    )
    if isinstance(exc, transient_types):
        return True
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "temporary failure in name resolution",
            "name resolution",
            "nodename nor servname provided",
            "getaddrinfo failed",
            "network is unreachable",
            "connection refused",
            "connection reset",
            "timed out",
        )
    )

class TelegramNotifier:
    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.enabled = bool(bot_token and chat_id)
        self._background_tasks: set[asyncio.Task] = set()
        if os.getenv("TELEGRAM_SIGNALS", "true").lower() == "false":
            self.enabled = False
            logger.info("Telegram signals disabled via config")

    def send(self, message: str, parse_mode: str = "Markdown") -> bool:
        if not self.enabled:
            return False

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            task = loop.create_task(self.send_async(message, parse_mode=parse_mode))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
            task.add_done_callback(self._handle_task_result)
            return True

        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": parse_mode
            }
            response = httpx.post(url, json=payload, timeout=5.0)
            return response.status_code == 200
        except Exception as e:
            if _is_transient_network_error(e):
                logger.info("Telegram notification skipped due to transient network issue: %s", e)
            else:
                logger.warning(f"Failed to send Telegram notification: {e}")
            return False

    async def send_async(self, message: str, parse_mode: str = "Markdown") -> bool:
        if not self.enabled:
            return False
        
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": parse_mode
        }
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, timeout=5.0)
                return response.status_code == 200
        except Exception as e:
            if _is_transient_network_error(e):
                logger.info("Async Telegram notification skipped due to transient network issue: %s", e)
            else:
                logger.warning(f"Failed to send async Telegram notification: {e}")
            return False

    def _handle_task_result(self, task: asyncio.Task) -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error(
                "Friction Opérationnelle : Échec de l'envoi de notification en arrière-plan : %s",
                exc,
            )
