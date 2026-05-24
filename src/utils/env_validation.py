from __future__ import annotations

import os
from typing import Iterable

from utils.exceptions import QuantFatal


def _missing(keys: Iterable[str], secrets: dict[str, str] | None = None) -> list[str]:
    secrets = secrets or {}
    return [key for key in keys if not (os.getenv(key) or secrets.get(key))]


def validate_runtime_env(mode: str, secrets: dict[str, str] | None = None) -> None:
    mode_upper = (mode or "PAPER").upper()
    secrets = secrets or {}

    required = ["TELEGRAM_BOT_TOKEN", "CHAT_ID", "ENCRYPTION_KEY"]
    if mode_upper in {"SHADOW", "PROD"}:
        required.extend(["CLOB_PRIVATE_KEY", "POLYGON_RPC_URL"])
    if mode_upper == "PROD":
        required.extend(["TELEGRAM_ADMIN_CHAT_IDS"])
    if mode_upper == "PROD" and not (secrets.get("OPENROUTER_API_KEY") or os.getenv("OPENROUTER_API_KEY")):
        raise QuantFatal("OPENROUTER_API_KEY is required for PROD mode.")

    missing = _missing(required, secrets)
    if missing:
        raise QuantFatal(f"Missing required environment variables for {mode_upper}: {', '.join(sorted(set(missing)))}")

    if mode_upper in {"SHADOW", "PROD"} and not secrets.get("CLOB_PRIVATE_KEY"):
        raise QuantFatal(f"CLOB_PRIVATE_KEY is required for {mode_upper} mode.")
