import re
from typing import Optional


SIGNAL_REGEX = re.compile(
    r"^(BUY|SELL|LONG|SHORT)\s+([A-Z0-9\-_]+)\s+@\s*(\d+\.?\d*)$",
    re.IGNORECASE,
)

_SEMANTIC_KEYWORDS = [
    "buy", "sell", "long", "short", "accumulate", "bid", "ask",
    "entry", "exit", "tp", "sl", "take profit", "stop loss",
    "signal", "alert", "setup", "trade", "position",
]


class SignalParser:
    @staticmethod
    def parse_deterministic(text: str) -> Optional[dict]:
        match = SIGNAL_REGEX.match(text.strip())
        if not match:
            return None
        return {
            "action": match.group(1).upper(),
            "asset": match.group(2).upper(),
            "price": float(match.group(3)),
            "source": "regex",
        }

    @staticmethod
    def parse_semantic(text: str) -> Optional[dict]:
        text_lower = text.lower()
        if not any(kw in text_lower for kw in _SEMANTIC_KEYWORDS):
            return None
        action = (
            "BUY"
            if any(w in text_lower for w in ["buy", "long", "accumulate", "bid"])
            else "SELL"
        )
        return {
            "action": action,
            "raw": text,
            "source": "lobstar_llm",
        }
