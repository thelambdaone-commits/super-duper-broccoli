from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Tuple

import httpx

from polymarket.execution.wallet_manager import PolymarketWalletManager

logger = logging.getLogger("PolymarketWalletJournal")

SCHEMA_VERSION = "2.2"
DATA_API_BASE = "https://data-api.polymarket.com"


@dataclass(frozen=True)
class WalletIdentity:
    eoa_address: str
    chat_id: str = ""
    wallet_name: str = ""
    proxy_address: Optional[str] = None

    @property
    def data_user(self) -> str:
        """The address Polymarket Data API expects (prefers proxy if available)."""
        return self.proxy_address or self.eoa_address


class PolymarketWalletJournal:
    """
    Core utility to reconcile real Polymarket state with the internal ledger.
    Fetches positions, activity, and balances across EOA and Proxy wallets.
    """

    def __init__(
        self,
        wallet_manager: Optional[PolymarketWalletManager | str | Path] = None,
    ) -> None:
        self.storage_path: Path | None = None
        self.wallet_manager: PolymarketWalletManager | None = None
        if isinstance(wallet_manager, (str, Path)):
            self.storage_path = Path(wallet_manager)
            return
        self.wallet_manager = wallet_manager or self._init_default_manager()

    def _init_default_manager(self) -> PolymarketWalletManager:
        from utils.vault_handler import VaultHandler

        vault = VaultHandler()
        return PolymarketWalletManager(
            vault_handler=vault,
            polygon_rpc_url=os.getenv("POLYGON_RPC_URL", ""),
        )

    def append(self, payload: Mapping[str, Any]) -> None:
        if self.storage_path is None:
            raise ValueError("storage_path is not configured for this journal")
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        with self.storage_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(dict(payload), ensure_ascii=True) + "\n")

    def latest(self) -> dict[str, Any]:
        if self.storage_path is None or not self.storage_path.exists():
            return {}
        lines = self.storage_path.read_text(encoding="utf-8").splitlines()
        if not lines:
            return {}
        return json.loads(lines[-1])

    async def fetch_snapshot(
        self,
        identity: WalletIdentity,
        balances: Mapping[str, Any] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        own_client = client is None
        http_client = client or httpx.AsyncClient(timeout=8.0)
        try:
            # 1. Fetch balances if not provided
            if balances is None:
                if self.wallet_manager is None:
                    self.wallet_manager = self._init_default_manager()
                balances = await self.wallet_manager.recuperer_soldes_on_chain(
                    identity.eoa_address, proxy_address=identity.proxy_address
                )

            # 2. Fetch data from Data API
            user = identity.data_user
            positions, closed_positions, activity, value_rows, api_errors = await self._fetch_data_api(http_client, user)
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
            api_errors=api_errors,
        )

    async def _fetch_data_api(
        self,
        client: httpx.AsyncClient,
        user: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
        params = {"user": user}
        responses = await asyncio.gather(
            client.get(f"{DATA_API_BASE}/positions", params={**params, "limit": 500, "sizeThreshold": 0}),
            client.get(f"{DATA_API_BASE}/closed-positions", params={**params, "limit": 500}),
            client.get(f"{DATA_API_BASE}/activity", params={**params, "limit": 500, "type": "TRADE"}),
            client.get(f"{DATA_API_BASE}/value", params=params),
            return_exceptions=True
        )
        
        results = []
        errors = []
        for i, resp in enumerate(responses):
            if isinstance(resp, Exception):
                results.append([])
                errors.append(f"Network error: {resp}")
            else:
                data, err = self._json_list_with_error(resp)
                results.append(data)
                if err:
                    errors.append(err)
                    
        return (results[0], results[1], results[2], results[3], errors)

    @staticmethod
    def _json_list_with_error(response: httpx.Response) -> tuple[list[dict[str, Any]], Optional[str]]:
        if response.status_code != 200:
            return [], f"API {response.status_code} at {response.url.path}"
        payload = response.json()
        return (payload if isinstance(payload, list) else []), None

    def build_snapshot(
        self,
        identity: WalletIdentity,
        *,
        positions: list[Mapping[str, Any]],
        closed_positions: list[Mapping[str, Any]],
        activity: list[Mapping[str, Any]],
        value_rows: list[Mapping[str, Any]],
        balances: Mapping[str, Any],
        api_errors: list[str] = None,
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
        
        errors = []
        balance_error = balances.get("error")
        if balance_error:
            errors.append({"component": "balances", "error": str(balance_error)})

        return {
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
            "api_errors": api_errors or [],
            "errors": errors,
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
            }
        }


def _to_float(value: Any, fallback: float = 0.0) -> float:
    if value is None:
        return fallback
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _slim_positions(positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove heavy metadata for telemetry storage."""
    return [
        {
            "ticker": p.get("ticker"),
            "size": p.get("size"),
            "pnl": p.get("cashPnl") or p.get("realizedPnl"),
        }
        for p in positions[:10]
    ]
