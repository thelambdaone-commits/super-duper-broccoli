from __future__ import annotations

import re

HEX_PRIVATE_KEY_RE = re.compile(r"^0x[a-fA-F0-9]{64}$")


def is_placeholder_secret(value: str | None) -> bool:
    if not value:
        return True
    text = value.strip()
    lowered = text.lower()
    return (
        lowered.startswith("0x_your_")
        or "your_ethereum_private_key_here" in lowered
        or "placeholder" in lowered
        or "replace_me" in lowered
        or lowered in {"0x", "0x0"}
    )


def normalize_private_key(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip()
    if is_placeholder_secret(cleaned):
        return None
    if cleaned.startswith("0x"):
        return cleaned if HEX_PRIVATE_KEY_RE.match(cleaned) else None
    if re.fullmatch(r"[a-fA-F0-9]{64}", cleaned):
        return f"0x{cleaned}"
    return None


def validate_private_key_or_raise(value: str | None, source: str = "unknown") -> str:
    key = normalize_private_key(value)
    if not key:
        raise ValueError(
            f"Invalid CLOB_PRIVATE_KEY from {source}. Expected a 32-byte hex key like 0x{('a'*64)}; "
            "placeholder values from .env.example are not accepted."
        )
    return key
