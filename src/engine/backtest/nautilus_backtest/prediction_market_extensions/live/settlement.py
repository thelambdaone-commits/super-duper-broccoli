from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping
from urllib.parse import quote
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class PolymarketTokenSettlement:
    condition_id: str
    token_id: str
    outcome: str
    winner: bool
    closed: bool
    price: Decimal | None


def split_polymarket_instrument_id(instrument_id: object) -> tuple[str, str]:
    raw = str(instrument_id).split(".", 1)[0]
    condition_id, separator, token_id = raw.rpartition("-")
    if not separator or not condition_id or not token_id:
        raise ValueError(f"Invalid Polymarket instrument ID: {instrument_id!r}")
    return condition_id, token_id


def _decimal_or_none(value: object) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _token_id(token: Mapping[str, Any]) -> str:
    return str(token.get("token_id") or token.get("asset_id") or token.get("id") or "")


def settlement_from_clob_market(
    market: Mapping[str, Any],
    *,
    token_id: str,
) -> PolymarketTokenSettlement | None:
    tokens = market.get("tokens")
    if not isinstance(tokens, list):
        return None

    closed = bool(market.get("closed"))
    condition_id = str(market.get("condition_id") or market.get("conditionId") or "")
    for raw_token in tokens:
        if not isinstance(raw_token, Mapping) or _token_id(raw_token) != str(token_id):
            continue
        price = _decimal_or_none(raw_token.get("price"))
        winner = raw_token.get("winner")
        if not isinstance(winner, bool) and closed and price in {Decimal("0"), Decimal("1")}:
            winner = price == Decimal("1")
        if not closed or not isinstance(winner, bool):
            return None
        return PolymarketTokenSettlement(
            condition_id=condition_id,
            token_id=str(token_id),
            outcome=str(raw_token.get("outcome") or ""),
            winner=winner,
            closed=closed,
            price=price,
        )

    return None


def fetch_clob_market(
    *,
    condition_id: str,
    base_url: str = "https://clob.polymarket.com",
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/markets/{quote(condition_id, safe='')}"
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "prediction-market-backtesting/1.0",
        },
    )
    with urlopen(request, timeout=float(timeout_seconds)) as response:
        payload = response.read().decode("utf-8")
    decoded = json.loads(payload)
    if not isinstance(decoded, dict):
        raise ValueError(f"Unexpected CLOB market response for {condition_id}: {type(decoded)!r}")
    return decoded


def fetch_clob_token_settlement(
    *,
    condition_id: str,
    token_id: str,
    base_url: str = "https://clob.polymarket.com",
    timeout_seconds: float = 5.0,
) -> PolymarketTokenSettlement | None:
    market = fetch_clob_market(
        condition_id=condition_id,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
    )
    return settlement_from_clob_market(market, token_id=token_id)
