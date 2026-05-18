from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger("TelegramTransportClient")


class TelegramTransportClient:
    def __init__(
        self,
        token: str,
        chat_id: str,
        client: Optional[httpx.Client] = None,
        base_url: str = "https://api.telegram.org",
    ) -> None:
        self.token = token
        self.chat_id = chat_id
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.Client(timeout=10.0)
        self._owns_client = client is None

    def send_raw_message(self, text: str, parse_mode: str = "MarkdownV2") -> bool:
        if not self.token or not self.chat_id:
            return False
        try:
            url = f"{self.base_url}/bot{self.token}/sendMessage"
            response = self.client.post(
                url,
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": parse_mode,
                },
            )
            response.raise_for_status()
            return True
        except Exception as exc:
            logger.error("Telegram transport failed: %s", exc)
            return False

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

