from __future__ import annotations

import asyncio
import hashlib
import json
import os
from typing import Any, Awaitable, Callable, TypeVar

T = TypeVar("T")


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def should_broadcast_message(category: str, text: str) -> bool:
    cleaned = "".join(text.split())
    msg_hash = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()

    filepath = "user_data/data/last_broadcast_hashes.json"
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    hashes = {}
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                hashes = json.load(f)
        except Exception:
            pass

    if hashes.get(category) == msg_hash:
        return False

    hashes[category] = msg_hash
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(hashes, f)
    except Exception:
        pass
    return True


async def run_blocking(name: str, func: Callable[..., T], *args: Any, timeout: float | None = None, **kwargs: Any) -> T:
    loop = asyncio.get_running_loop()
    future = loop.run_in_executor(None, lambda: func(*args, **kwargs))
    if timeout is None:
        return await future
    return await asyncio.wait_for(future, timeout=timeout)


async def _fetch_rpc_blocking(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    def _call() -> dict[str, Any]:
        import requests

        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        return resp.json()

    return await asyncio.to_thread(_call)


async def check_rpc_dry_run(rpc_url: str) -> dict[str, Any]:
    payload = {"jsonrpc": "2.0", "method": "eth_blockNumber", "params": [], "id": 1}
    return await _fetch_rpc_blocking(rpc_url, payload)
