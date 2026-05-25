import json
import os
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache
from typing import Any


CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "config")
OPENVIKING_CONFIG_PATH = os.path.join(CONFIG_DIR, "openviking.json")

DEFAULT_ENDPOINTS = [
    "/api/v1/search/search",
    "/api/v1/search/find",
    "/api/v1/search/grep",
    "/api/v1/search/glob",
]


@lru_cache(maxsize=1)
def load_openviking_config(path: str = OPENVIKING_CONFIG_PATH) -> dict[str, Any]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def is_enabled() -> bool:
    return os.getenv("OPENVIKING_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


def _resolve_base_url() -> str:
    config = load_openviking_config()
    base_url = (
        os.getenv("OPENVIKING_URL")
        or config.get("url")
        or config.get("base_url")
        or "http://127.0.0.1:1933"
    )
    return str(base_url).rstrip("/")


def _build_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    api_key = os.getenv("OPENVIKING_API_KEY") or load_openviking_config().get("api_key")
    account = os.getenv("OPENVIKING_ACCOUNT") or load_openviking_config().get("account")
    user = os.getenv("OPENVIKING_USER") or load_openviking_config().get("user")
    if api_key:
        headers["X-OpenViking-Api-Key"] = str(api_key)
    if account:
        headers["X-OpenViking-Account"] = str(account)
    if user:
        headers["X-OpenViking-User"] = str(user)
    return headers


def _request_json(method: str, url: str, payload: dict[str, Any] | None = None, timeout: float = 5.0) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method.upper(), headers=_build_headers())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return json.loads(body) if body else {}
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return {}


def search_context(query: str, limit: int = 5, timeout: float = 5.0) -> list[dict[str, Any]]:
    base_url = _resolve_base_url()
    safe_query = query.strip()
    if not safe_query:
        return []
    for endpoint in DEFAULT_ENDPOINTS:
        payload = {"query": safe_query, "limit": max(1, min(int(limit), 20))}
        response = _request_json("POST", f"{base_url}{endpoint}", payload=payload, timeout=timeout)
        items = response.get("results") or response.get("data") or response.get("items")
        if isinstance(items, list) and items:
            return items
        if isinstance(response, dict) and response:
            return [response]
    return []


def build_openviking_context(
    query: str,
    component: str = "",
    limit: int = 5,
    timeout: float = 5.0,
) -> dict[str, Any]:
    if not is_enabled():
        return {"enabled": False, "available": False, "results": []}

    results = search_context(query=query, limit=limit, timeout=timeout)
    return {
        "enabled": True,
        "available": bool(results),
        "endpoint": _resolve_base_url(),
        "component": component,
        "query": query[:200],
        "result_count": len(results),
        "results": results[:limit],
    }
