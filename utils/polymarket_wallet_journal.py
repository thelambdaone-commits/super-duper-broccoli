from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import httpx


DATA_API_BASE = "https://data-api.polymarket.com"
SCHEMA_VERSION = 1


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _slim_activity(activity: list[Mapping[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in activity[:limit]:
        rows.append(
            {
                "timestamp": item.get("timestamp"),
                "side": item.get("side"),
                "title": item.get("title"),
                "outcome": item.get("outcome"),
                "size": _to_float(item.get("size")),
                "price": _to_float(item.get("price")),
                "usdc_size": _to_float(item.get("usdcSize")),
                "tx": item.get("transactionHash"),
                "asset": item.get("asset"),
            }
        )
    return rows


def _slim_positions(positions: list[Mapping[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in positions[:limit]:
        rows.append(
            {
                "title": item.get("title"),
                "outcome": item.get("outcome"),
                "size": _to_float(item.get("size")),
                "avg_price": _to_float(item.get("avgPrice")),
                "cur_price": _to_float(item.get("curPrice")),
                "current_value": _to_float(item.get("currentValue")),
                "cash_pnl": _to_float(item.get("cashPnl")),
                "realized_pnl": _to_float(item.get("realizedPnl")),
                "redeemable": bool(item.get("redeemable")),
                "mergeable": bool(item.get("mergeable")),
                "asset": item.get("asset"),
                "condition_id": item.get("conditionId"),
            }
        )
    return rows


@dataclass(frozen=True)
class WalletIdentity:
    eoa_address: str
    proxy_address: str = ""
    chat_id: str = ""
    wallet_name: str = ""

    @property
    def data_user(self) -> str:
        return (self.proxy_address or self.eoa_address).lower()


class PolymarketWalletJournal:
    """Append-only wallet telemetry journal for fast Polymarket reconciliation."""

    def __init__(self, path: str | os.PathLike[str] = "data/wallet.jsonl") -> None:
        self.path = Path(path)

    async def fetch_snapshot(
        self,
        identity: WalletIdentity,
        *,
        balances: Mapping[str, Any] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        own_client = client is None
        http_client = client or httpx.AsyncClient(timeout=8.0)
        try:
            user = identity.data_user
            positions, closed_positions, activity, value_rows = await self._fetch_data_api(http_client, user)
        finally:
            if own_client:
                await http_client.aclose()

        return self.build_snapshot(
            identity,
            positions=positions,
            closed_positions=closed_positions,
            activity=activity,
            value_rows=value_rows,
            balances=balances or {},
        )

    async def _fetch_data_api(
        self,
        client: httpx.AsyncClient,
        user: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        params = {"user": user}
        responses = await asyncio.gather(
            client.get(f"{DATA_API_BASE}/positions", params={**params, "limit": 500, "sizeThreshold": 0}),
            client.get(f"{DATA_API_BASE}/closed-positions", params={**params, "limit": 500}),
            client.get(f"{DATA_API_BASE}/activity", params={**params, "limit": 500, "type": "TRADE"}),
            client.get(f"{DATA_API_BASE}/value", params=params),
        )
        return tuple(self._json_list(response) for response in responses)  # type: ignore[return-value]

    @staticmethod
    def _json_list(response: httpx.Response) -> list[dict[str, Any]]:
        if response.status_code != 200:
            return []
        payload = response.json()
        return payload if isinstance(payload, list) else []

    def build_snapshot(
        self,
        identity: WalletIdentity,
        *,
        positions: list[Mapping[str, Any]],
        closed_positions: list[Mapping[str, Any]],
        activity: list[Mapping[str, Any]],
        value_rows: list[Mapping[str, Any]],
        balances: Mapping[str, Any],
    ) -> dict[str, Any]:
        closed_realized = sum(_to_float(row.get("realizedPnl")) for row in closed_positions)
        closed_wins = sum(1 for row in closed_positions if _to_float(row.get("realizedPnl")) > 0)
        closed_losses = sum(1 for row in closed_positions if _to_float(row.get("realizedPnl")) < 0)
        open_cash_pnl = sum(_to_float(row.get("cashPnl")) for row in positions)
        open_current_value = sum(_to_float(row.get("currentValue")) for row in positions)
        volume = sum(abs(_to_float(row.get("usdcSize"), _to_float(row.get("size")) * _to_float(row.get("price")))) for row in activity)

        usdc_direct = _to_float(balances.get("usdc_direct"))
        usdc_proxy = _to_float(balances.get("usdc_proxy"))
        gas_pol = _to_float(balances.get("eth_balance"))
        wallet_value = _to_float(value_rows[0].get("value")) if value_rows else open_current_value
        total_capital = usdc_direct + usdc_proxy + wallet_value

        latest_activity_ts = max((_to_float(row.get("timestamp")) for row in activity), default=0.0)
        balance_error = balances.get("error")
        snapshot = {
            "schema_version": SCHEMA_VERSION,
            "ts": time.time(),
            "wallet": {
                "chat_id": identity.chat_id,
                "name": identity.wallet_name,
                "eoa": identity.eoa_address.lower(),
                "proxy": identity.proxy_address.lower() if identity.proxy_address else "",
                "data_user": identity.data_user,
            },
            "balances": {
                "usdc_direct": usdc_direct,
                "polymarket_pusd": usdc_proxy,
                "open_positions_value": wallet_value,
                "gas_pol": gas_pol,
                "total_capital": total_capital,
            },
            "pnl": {
                "closed_realized": closed_realized,
                "open_cash_pnl": open_cash_pnl,
                "closed_wins": closed_wins,
                "closed_losses": closed_losses,
                "closed_win_rate": closed_wins / len(closed_positions) if closed_positions else 0.0,
            },
            "counts": {
                "open_positions": len(positions),
                "closed_positions": len(closed_positions),
                "activity": len(activity),
            },
            "flow": {
                "trade_volume_usdc": volume,
                "latest_activity_ts": latest_activity_ts,
            },
            "samples": {
                "open_positions": _slim_positions(list(positions)),
                "closed_positions": _slim_positions(list(closed_positions)),
                "activity": _slim_activity(list(activity)),
            },
            "sources": {
                "positions": f"{DATA_API_BASE}/positions",
                "closed_positions": f"{DATA_API_BASE}/closed-positions",
                "activity": f"{DATA_API_BASE}/activity",
                "value": f"{DATA_API_BASE}/value",
            },
        }
        if balance_error:
            snapshot["errors"] = [{"component": "balances", "error": str(balance_error)}]
        return snapshot

    def append(self, snapshot: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(snapshot, separators=(",", ":"), sort_keys=True))
            handle.write("\n")

    def latest(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        last_line = ""
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    last_line = line
        return json.loads(last_line) if last_line else None
