import json
import logging
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

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def analyser_signal_contextuel(self, texte_signal: str) -> Optional[dict]:
        try:
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

            raw_content = response.choices[0].message.content.strip()
            data = json.loads(raw_content)

            if "error" in data:
                return None

            return data

        except Exception as e:
            logging.getLogger("LobstarAgent").error(f"Semantic inference failed: {e}")
            return None
