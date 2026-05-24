from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_DIR = Path(__file__).resolve().parent.parent


def build_trading_client(host: str, chain_id: int):
    """
    Authenticated CLOB client (Level 2), matching upstream usage:

        client = ClobClient(host, key=..., chain_id=..., signature_type=..., funder=...)
        client.set_api_creds(client.derive_api_key())

    See https://docs.polymarket.com/trading/clients/l1 and /l2.
    """
    load_dotenv(_PROJECT_DIR / ".env", override=False)
    from py_clob_client_v2 import ClobClient

    key = os.environ.get("POLYMARKET_PRIVATE_KEY") or os.environ.get("PRIVATE_KEY")
    if not key:
        raise RuntimeError("Set PRIVATE_KEY or POLYMARKET_PRIVATE_KEY in .env or environment.")

    funder = (
        os.environ.get("POLYMARKET_FUNDER")
        or os.environ.get("POLYMARKET_PROXY_WALLET_ADDRESS")
        or os.environ.get("PROXY_WALLET_ADDRESS")
    )
    if not funder:
        raise RuntimeError("Set POLYMARKET_FUNDER or POLYMARKET_PROXY_WALLET_ADDRESS in .env or environment.")

    sig = int(os.environ.get("POLYMARKET_SIGNATURE_TYPE", "2" if funder else "0"))
    client = ClobClient(
        host,
        key=key,
        chain_id=chain_id,
        signature_type=sig,
        funder=funder,
    )
    creds = client.derive_api_key()
    if creds is None:
        raise RuntimeError(
            "Failed to derive CLOB API credentials; check private key, funder, signature_type, and chain_id."
        )
    client.set_api_creds(creds)
    return client


def funder_address() -> str:
    load_dotenv(_PROJECT_DIR / ".env", override=False)
    a = (
        os.environ.get("POLYMARKET_FUNDER")
        or os.environ.get("POLYMARKET_PROXY_WALLET_ADDRESS")
        or os.environ.get("PROXY_WALLET_ADDRESS")
    )
    if not a:
        raise RuntimeError("POLYMARKET_FUNDER or POLYMARKET_PROXY_WALLET_ADDRESS is not set.")
    return a
