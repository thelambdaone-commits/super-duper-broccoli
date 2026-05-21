from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

import httpx

logger = logging.getLogger("MetsTelegramScraper")

TELEGRAM_API_BASE = "https://api.telegram.org"
TELEGRAM_BOT_TOKEN = ""
METS_CHANNEL_IDS = ""
METS_KEYWORDS = "Mets,New York Mets,MLB,baseball,game,score,odds,pick,predict,parlay,moneyline,spread,over,under"


@dataclass(frozen=True)
class MetsTelegramScraperConfig:
    api_base: str = TELEGRAM_API_BASE
    bot_token: str = TELEGRAM_BOT_TOKEN
    channel_ids: tuple[int, ...] = ()
    poll_interval_seconds: float = 10.0
    timeout_seconds: float = 15.0
    max_updates: int = 100
    allowed_updates: tuple[str, ...] = ("message", "channel_post")
    keywords: tuple[str, ...] = ()


class MetsTelegramScraper:
    def __init__(
        self,
        config: Optional[MetsTelegramScraperConfig] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        raw_ids = (
            config.channel_ids
            if config and config.channel_ids
            else _parse_channel_ids(METS_CHANNEL_IDS)
        )
        self.channel_ids: set[int] = set(raw_ids)
        self.config = config or MetsTelegramScraperConfig(
            channel_ids=tuple(self.channel_ids),
            keywords=tuple(
                kw.strip().lower()
                for kw in METS_KEYWORDS.split(",")
                if kw.strip()
            ),
        )
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(self.config.timeout_seconds)
        )
        self._owns_client = client is None
        self._running = False
        self._offset: Optional[int] = None

    @property
    def _bot_url(self) -> str:
        return f"{self.config.api_base.rstrip('/')}/bot{self.config.bot_token}"

    async def close(self) -> None:
        self._running = False
        if self._owns_client:
            await self._client.aclose()

    def add_channel(self, channel_id: int) -> None:
        self.channel_ids.add(channel_id)

    async def fetch_updates(self) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "timeout": 5,
            "limit": self.config.max_updates,
            "allowed_updates": json.dumps(list(self.config.allowed_updates)),
        }
        if self._offset is not None:
            params["offset"] = self._offset

        response = await self._client.get(
            f"{self._bot_url}/getUpdates", params=params
        )
        response.raise_for_status()
        data = response.json()
        return data.get("result", [])

    def filter_mets_messages(
        self, updates: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        for update in updates:
            update_id = update.get("update_id")
            if update_id is not None:
                self._offset = update_id + 1

            msg = update.get("channel_post") or update.get("message")
            if not msg:
                continue

            chat_id = msg.get("chat", {}).get("id")
            if self.channel_ids and chat_id not in self.channel_ids:
                continue

            text = (msg.get("text") or msg.get("caption") or "").lower()
            if not self._is_mets_related(text):
                continue

            msg["_scraped_at"] = time.time()
            msg["_update_id"] = update.get("update_id")
            msg["_is_mets_related"] = True
            messages.append(msg)

        return messages

    def _is_mets_related(self, text: str) -> bool:
        if not text:
            return False
        mets_patterns = [
            r"\bmets\b",
            r"\bnew york mets\b",
            r"#mets",
            r"#ny mets",
            r"#lgm",
            r"#truenymets",
            r"#metswin",
        ]
        for pat in mets_patterns:
            if re.search(pat, text, re.IGNORECASE):
                return True
        if self.config.keywords:
            text_lower = text.lower()
            for kw in self.config.keywords:
                if kw in text_lower:
                    return True
        return False

    def parse_message(
        self, msg: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        text = (msg.get("text") or msg.get("caption") or "").strip()
        if not text:
            return None

        chat = msg.get("chat", {})
        parsed: dict[str, Any] = {
            "source": "mets_telegram",
            "chat_id": chat.get("id"),
            "chat_title": chat.get("title", chat.get("username", "")),
            "message_id": msg.get("message_id"),
            "text": text,
            "timestamp": msg.get("date"),
            "scraped_at": msg.get("_scraped_at"),
            "has_entities": bool(
                msg.get("entities") or msg.get("caption_entities")
            ),
        }

        entities = msg.get("entities") or msg.get("caption_entities") or []
        if entities:
            parsed["entities"] = [
                {
                    "type": e.get("type"),
                    "offset": e.get("offset"),
                    "length": e.get("length"),
                }
                for e in entities
            ]

        mets_mentions = self._extract_mets_entities(text)
        if mets_mentions:
            parsed["mets_entities"] = mets_mentions

        return parsed

    def _extract_mets_entities(
        self, text: str
    ) -> list[dict[str, Any]]:
        entities: list[dict[str, Any]] = []
        game_pattern = r"(?:Mets|NYM|New York Mets)\s+(?:vs\.?|@|vs|against)\s+([A-Za-z\s]+?)(?:\s+\d|$|,)"

        for match in re.finditer(game_pattern, text, re.IGNORECASE):
            entities.append(
                {
                    "type": "game_mention",
                    "opponent": match.group(1).strip(),
                    "matched_text": match.group(0).strip(),
                }
            )

        score_pattern = r"(?:Mets|NYM)\s+(\d+)\s*[-–]\s*(\d+)"
        for match in re.finditer(score_pattern, text, re.IGNORECASE):
            entities.append(
                {
                    "type": "score",
                    "mets_score": int(match.group(1)),
                    "opponent_score": int(match.group(2)),
                    "matched_text": match.group(0).strip(),
                }
            )

        odds_pattern = r"(?:Mets|NYM)\s+([+-]\d+)"
        for match in re.finditer(odds_pattern, text):
            entities.append(
                {
                    "type": "odds",
                    "value": match.group(1),
                    "matched_text": match.group(0).strip(),
                }
            )

        return entities

    async def poll_once(
        self, callback=None
    ) -> list[dict[str, Any]]:
        updates = await self.fetch_updates()
        messages = self.filter_mets_messages(updates)

        events: list[dict[str, Any]] = []
        for msg in messages:
            parsed = self.parse_message(msg)
            if parsed:
                events.append(parsed)
                logger.info(
                    "Mets message from %s: %.80s",
                    parsed.get("chat_title", "unknown"),
                    parsed.get("text", ""),
                )
                if callback:
                    maybe = callback(parsed)
                    if asyncio.iscoroutine(maybe):
                        await maybe
        return events

    async def run(self, callback=None) -> None:
        self._running = True
        logger.info(
            "Starting Mets Telegram scraper for %d channel(s)",
            len(self.channel_ids),
        )
        while self._running:
            try:
                await self.poll_once(callback=callback)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Mets scraper poll failed: %s", exc)
            await asyncio.sleep(self.config.poll_interval_seconds)

    def stop(self) -> None:
        self._running = False


def _parse_channel_ids(raw: str) -> tuple[int, ...]:
    if not raw:
        return ()
    ids: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.append(int(part))
        except ValueError:
            logger.warning("Ignoring invalid channel id: %s", part)
    return tuple(ids)
