from __future__ import annotations

from typing import Any


def extract_live_clob_token_ids(markets: list[Any], limit: int = 30) -> list[str]:
    token_ids: list[str] = []
    seen: set[str] = set()
    for market in markets:
        for token in getattr(market, "tokens", []) or []:
            token_id = str(token.get("token_id", "")).strip()
            if not token_id or token_id in seen:
                continue
            seen.add(token_id)
            token_ids.append(token_id)
            if len(token_ids) >= limit:
                return token_ids
    return token_ids
