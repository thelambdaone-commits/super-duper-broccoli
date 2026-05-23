import os
import httpx
import time
import logging
from telegram import Update
from telegram.constants import ParseMode
from utils.rpc_provider import get_rpc_url, resolve_rpc_with_fallback

logger = logging.getLogger("SystemHandlers")

class SystemHandlers:
    def __init__(self, bot_token: str, ledger=None, hmm=None, risk=None):
        self.bot_token = bot_token
        self._ledger = ledger
        self._hmm = hmm
        self._risk = risk

    async def cmd_status(self, update: Update, _context) -> str:
        # Simplified for demonstration, actual implementation will be more detailed
        return "System Status: Online"

    async def cmd_check(self, update: Update, _context) -> str:
        results: list[str] = ["*API Connectivity Check*"]
        timeout = httpx.Timeout(5.0, connect=3.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            try:
                telegram_token_prefix = self.bot_token[:8] + "..."
                results.append(f"\n*Telegram:* token={telegram_token_prefix}")

                vault_ok = bool(os.getenv("VAULT_TOKEN"))
                results.append(f"*Vault:* {'OK' if vault_ok else 'MISSING TOKEN'}")

                clob_url = "https://clob.polymarket.com"
                try:
                    r = await client.get(f"{clob_url}/", timeout=3.0)
                    clob_status = "OK" if r.status_code < 500 else f"HTTP {r.status_code}"
                except Exception as e:
                    clob_status = f"FAIL ({e.__class__.__name__})"
                results.append(f"*Polymarket CLOB:* {clob_status}")

                # ... (add other checks here)
                
                chains = []
                for chain_key in ("polygon", "eth", "sol", "arb", "opt", "base"):
                    primary = get_rpc_url(chain_key)
                    fallback = resolve_rpc_with_fallback(chain_key)
                    if primary:
                        chains.append(f"  {chain_key.capitalize()}: env ({primary[:30]}...)")
                    elif fallback:
                        chains.append(f"  {chain_key.capitalize()}: fallback ({fallback[:30]}...)")
                    else:
                        chains.append(f"  {chain_key.capitalize()}: not configured")
                if chains:
                    results.append("\n*RPC Endpoints:*")
                    results.extend(chains)

            except Exception as e:
                results.append(f"Check Error: {e}")

        return "\n".join(results)
