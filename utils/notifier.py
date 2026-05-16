import logging
import os
import httpx
from typing import Optional

logger = logging.getLogger("Notifier")

class TelegramNotifier:
    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.enabled = bool(bot_token and chat_id)
        if os.getenv("TELEGRAM_SIGNALS", "true").lower() == "false":
            self.enabled = False
            logger.info("Telegram signals disabled via config")

    def send(self, message: str, parse_mode: str = "Markdown") -> bool:
        if not self.enabled:
            return False
        
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": parse_mode
        }
        try:
            # Synchronous post for simplicity in various contexts
            response = httpx.post(url, json=payload, timeout=5.0)
            return response.status_code == 200
        except Exception as e:
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
            logger.warning(f"Failed to send async Telegram notification: {e}")
            return False
