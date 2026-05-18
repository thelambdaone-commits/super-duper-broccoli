from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.wallet_manager import PolymarketWalletManager
from utils.credential_manager import CredentialManager
from utils.polymarket_wallet_journal import PolymarketWalletJournal, WalletIdentity
from utils.vault_handler import VaultHandler


def resolve_wallet(chat_id: str) -> WalletIdentity:
    mgr = CredentialManager()
    wallet_type = mgr.get_active_wallet_type(chat_id)
    user_data = mgr.load_user(chat_id, wallet_type)
    return WalletIdentity(
        chat_id=chat_id,
        wallet_name=wallet_type,
        eoa_address=user_data.get("address", ""),
        proxy_address=user_data.get("proxy_wallet", ""),
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description="Append a Polymarket wallet snapshot to data/wallet.jsonl")
    parser.add_argument("--chat-id", default=os.getenv("TELEGRAM_OWNER_CHAT_ID") or os.getenv("CHAT_ID", ""))
    parser.add_argument("--output", default="data/wallet.jsonl")
    parser.add_argument("--print", action="store_true", dest="print_snapshot")
    args = parser.parse_args()

    load_dotenv()
    identity = resolve_wallet(str(args.chat_id))
    if not identity.eoa_address:
        raise SystemExit(f"No wallet found for chat_id={args.chat_id}")

    polygon_rpc_url = os.getenv("POLYGON_RPC_URL") or os.getenv("RPC_URL") or ""
    wallet_manager = PolymarketWalletManager(
        vault_handler=VaultHandler(),
        polygon_rpc_url=polygon_rpc_url,
    )
    try:
        balances = await asyncio.wait_for(
            wallet_manager.recuperer_soldes_on_chain(
                identity.eoa_address,
                proxy_address=identity.proxy_address,
            ),
            timeout=8.0,
        )
    except Exception as exc:
        balances = {"usdc_direct": 0.0, "usdc_proxy": 0.0, "eth_balance": 0.0, "error": type(exc).__name__}

    journal = PolymarketWalletJournal(args.output)
    snapshot = await journal.fetch_snapshot(identity, balances=balances)
    journal.append(snapshot)

    if args.print_snapshot:
        print(json.dumps(snapshot, indent=2, sort_keys=True))
    else:
        print(
            json.dumps(
                {
                    "ok": True,
                    "path": args.output,
                    "wallet": snapshot["wallet"],
                    "total_capital": snapshot["balances"]["total_capital"],
                    "closed_realized": snapshot["pnl"]["closed_realized"],
                    "activity": snapshot["counts"]["activity"],
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
