import json
import logging
import time
from typing import Optional

from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type


LOBSTAR_SYSTEM_PROMPT = (
    "You are LOBSTAR Wilde, an autonomous HFT risk engine specialized in Polymarket and Solana CLOB. "
    "Your task is to parse unstructured Telegram signals and output a strict JSON object. "
    "JSON Format: {\"ticker\": str, \"side\": \"YES\"|\"NO\"|\"BUY\"|\"SELL\", "
    "\"price_limite\": float, \"size\": float, \"confidence\": float} "
    "If the signal is invalid, unreadable, or missing critical data, return exactly: "
    "{\"error\": \"INVALID_SIGNAL\"} "
    "Do not include conversational prose, markdown blocks, or thinking tags. Output ONLY raw JSON."
)


class LobstarAgent:
    def __init__(self, api_key: str) -> None:
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1",
        )
        self._cache: dict[str, tuple[float, Optional[dict]]] = {}
        self._consecutive_failures = 0
        self._fallback_active = False
        self._next_health_check = 0.0

    def _regex_fallback(self, texte_signal: str) -> Optional[dict]:
        import re
        match = re.search(r"\b(BUY|SELL|YES|NO)\s+([A-Za-z0-9_]+)\b", texte_signal, re.IGNORECASE)
        if match:
            side = match.group(1).upper()
            ticker = match.group(2).upper()
            return {"ticker": ticker, "side": side, "price_limite": 0.0, "size": 0.0, "confidence": 0.5}
        return None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def _call_groq(self, texte_signal: str) -> dict:
        response = await self.client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": LOBSTAR_SYSTEM_PROMPT},
                {"role": "user", "content": texte_signal},
            ],
            temperature=0.0,
            max_tokens=200,
            response_format={"type": "json_object"},
        )
        return json.loads(response.choices[0].message.content.strip())

    async def analyser_signal_contextuel(self, texte_signal: str) -> Optional[dict]:
        now = time.time()
        # Clean expired keys (60 seconds expiration TTL)
        self._cache = {k: (ts, val) for k, (ts, val) in self._cache.items() if now - ts < 60.0}

        if texte_signal in self._cache:
            logging.getLogger("LobstarAgent").info("Semantic inference cache hit for signal context")
            return self._cache[texte_signal][1]

        if self._fallback_active:
            if now < self._next_health_check:
                return self._regex_fallback(texte_signal)
            else:
                self._fallback_active = False

        try:
            data = await self._call_groq(texte_signal)
            self._consecutive_failures = 0

            if "error" in data:
                self._cache[texte_signal] = (now, None)
                return None

            self._cache[texte_signal] = (now, data)
            return data

        except Exception as e:
            self._consecutive_failures += 1
            logging.getLogger("LobstarAgent").error(f"Semantic inference failed (attempt {self._consecutive_failures}): {e}")
            if self._consecutive_failures >= 3:
                self._fallback_active = True
                self._next_health_check = now + 300.0
                logging.getLogger("LobstarAgent").critical("Groq API failed 3 times. DETERMINISTIC FALLBACK ACTIVATED for 5 minutes.")
            
            return self._regex_fallback(texte_signal)
