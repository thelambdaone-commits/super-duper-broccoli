#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from py_clob_client import ClobClient, OrderArgs, PartialCreateOrderOptions

from utils.vault_handler import VaultHandler


def _build_client(secrets: dict[str, str]) -> ClobClient:
    private_key = secrets["CLOB_PRIVATE_KEY"]
    funder = secrets.get("POLYMARKET_PROXY_WALLET_ADDRESS") or None
    
    # LOBSTAR V2: Prioritize explicit signature type from environment
    # py_clob_client_v2 supports POLY_1271=3 for deposit-wallet flows.
    signature_type = 3 if funder else 0
    env_sig = os.getenv("POLYMARKET_SIGNATURE_TYPE")
    if env_sig is not None:
        try:
            signature_type = int(env_sig)
        except ValueError:
            pass

    host = secrets.get("POLYMARKET_CLOB_HTTP_URL", "https://clob.polymarket.com")
    chain_id = int(os.getenv("CHAIN_ID", "137"))
    return ClobClient(
        host=host,
        key=private_key,
        chain_id=chain_id,
        signature_type=signature_type,
        funder=funder,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and sign a live Polymarket CLOB order without posting it.")
    parser.add_argument("--token-id", required=True, help="Outcome token_id (asset_id)")
    parser.add_argument("--side", choices=("BUY", "SELL"), required=True)
    parser.add_argument("--price", type=float, required=True)
    parser.add_argument("--size", type=float, required=True)
    args = parser.parse_args()

    os.environ.setdefault("EXECUTION_MODE", "PROD")
    secrets = VaultHandler().fetch_quantum_secrets()
    client = _build_client(secrets)

    signed = client.create_order(
        OrderArgs(
            token_id=args.token_id,
            price=float(args.price),
            size=float(args.size),
            side=args.side,
        ),
        PartialCreateOrderOptions(),
    )

    funder = secrets.get("POLYMARKET_PROXY_WALLET_ADDRESS")
    sig_type = 2 if funder else 0
    env_sig = os.getenv("POLYMARKET_SIGNATURE_TYPE")
    if env_sig is not None:
        try:
            sig_type = int(env_sig)
        except ValueError:
            pass

    summary = {
        "ok": True,
        "posted": False,
        "host": secrets.get("POLYMARKET_CLOB_HTTP_URL", "https://clob.polymarket.com"),
        "token_id": args.token_id,
        "side": args.side,
        "price": args.price,
        "size": args.size,
        "signature_type": sig_type,
        "has_funder": bool(funder),
        "signed_order_fields": sorted(list(signed.keys())) if isinstance(signed, dict) else str(type(signed)),
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
