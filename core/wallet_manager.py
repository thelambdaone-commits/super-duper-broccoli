import logging
import re
from typing import Any, Dict, Tuple

import httpx
from eth_account import Account
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger("LOBSTAR_WalletManager")

Account.enable_unaudited_hdwallet_features()

PRIVATE_KEY_RE = re.compile(r"^(?:0x)?[0-9a-fA-F]{64}$")


class PolymarketWalletManager:
    """RAM-only Polymarket wallet manager for Telegram private-chat imports."""

    ERC20_BALANCE_OF_SELECTOR = "0x70a08231"

    def __init__(self, vault_handler: Any, polygon_rpc_url: str = "") -> None:
        self.vault = vault_handler
        self.rpc_url = polygon_rpc_url
        self.usdc_polygon_contract = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"

    @staticmethod
    def is_private_key(text: str) -> bool:
        return bool(PRIVATE_KEY_RE.match(text.strip()))

    @staticmethod
    def is_seed_phrase(text: str) -> bool:
        words = [word for word in text.strip().split() if word]
        return len(words) in {12, 24} and all(re.fullmatch(r"[a-zA-Z]+", word) for word in words)

    @classmethod
    def looks_like_wallet_secret(cls, text: str) -> bool:
        return cls.is_private_key(text) or cls.is_seed_phrase(text)

    def importer_via_cle_privee(self, private_key: str) -> Tuple[str, str]:
        try:
            normalized = private_key.strip()
            if normalized.startswith("0x"):
                normalized = normalized[2:]
            compte = Account.from_key(normalized)
            adresse_publique = compte.address
            logger.info("Wallet private key imported for %s...%s", adresse_publique[:6], adresse_publique[-4:])
            return adresse_publique, f"0x{normalized}"
        except Exception as exc:
            logger.warning("Invalid private key import attempt: %s", exc)
            raise ValueError("Format de cle privee invalide.") from exc

    def importer_via_seed_phrase(self, seed_phrase: str, account_index: int = 0) -> Tuple[str, str]:
        try:
            path = f"m/44'/60'/0'/0/{account_index}"
            compte = Account.from_mnemonic(seed_phrase.strip(), account_path=path)
            adresse_publique = compte.address
            logger.info("Seed phrase derived for %s...%s using %s", adresse_publique[:6], adresse_publique[-4:], path)
            return adresse_publique, compte.key.hex()
        except Exception as exc:
            logger.warning("Invalid seed phrase import attempt: %s", exc)
            raise ValueError("Seed phrase invalide ou chemin de derivation corrompu.") from exc

    async def recuperer_soldes_on_chain(self, wallet_address: str) -> Dict[str, float]:
        if not self.rpc_url:
            return {"usdc_balance": 0.0, "eth_balance": 0.0}

        eth_balance = 0.0
        usdc_balance = 0.0

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                eth_payload = {
                    "jsonrpc": "2.0",
                    "method": "eth_getBalance",
                    "params": [wallet_address, "latest"],
                    "id": 1,
                }
                eth_response = await client.post(self.rpc_url, json=eth_payload)
                eth_response.raise_for_status()
                eth_result = eth_response.json().get("result", "0x0")
                eth_balance = int(eth_result, 16) / 1e18

                normalized_address = wallet_address.lower().replace("0x", "")
                usdc_payload = {
                    "jsonrpc": "2.0",
                    "method": "eth_call",
                    "params": [
                        {
                            "to": self.usdc_polygon_contract,
                            "data": f"{self.ERC20_BALANCE_OF_SELECTOR}{normalized_address.zfill(64)}",
                        },
                        "latest",
                    ],
                    "id": 2,
                }
                usdc_response = await client.post(self.rpc_url, json=usdc_payload)
                usdc_response.raise_for_status()
                usdc_result = usdc_response.json().get("result", "0x0")
                usdc_balance = int(usdc_result, 16) / 1e6
        except Exception as exc:
            logger.debug("Wallet balance RPC lookup failed: %s", exc)

        return {"usdc_balance": float(usdc_balance), "eth_balance": float(eth_balance)}

    def generer_layout_telegram(
        self,
        wallet_name: str,
        wallet_address: str,
        soldes: Dict[str, Any],
        total_connections: int,
    ) -> Tuple[str, InlineKeyboardMarkup]:
        adresse_tronquee = f"`{wallet_address[:8]}...{wallet_address[-6:]}`"
        text = (
            "🎯 *Polymarket*\n"
            "────────────────────────\n"
            "✅ *Connecte*\n"
            f"🔑 *Wallet actif* : `{wallet_name}`\n"
            f"📬 *Adresse* : {adresse_tronquee}\n"
            f"💵 *Solde Polymarket* : `{float(soldes.get('usdc_balance', 0.0)):.2f} USDC`\n"
            f"👛 *Actifs wallet* : `{float(soldes.get('eth_balance', 0.0)):.4f} ETH`\n"
            f"💾 *Connexions sauvegardees* : `{total_connections}`\n"
            "────────────────────────"
        )
        reply_markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("📜 Historique", callback_data="wallet_history"),
                    InlineKeyboardButton("📋 Ordres", callback_data="wallet_orders"),
                ],
                [
                    InlineKeyboardButton("📊 Positions", callback_data="wallet_positions"),
                    InlineKeyboardButton("💰 PnL", callback_data="wallet_pnl"),
                ],
                [
                    InlineKeyboardButton("🔄 Rafraichir", callback_data="wallet_refresh"),
                    InlineKeyboardButton("🔑 Voir cle privee", callback_data="wallet_show_key"),
                ],
                [
                    InlineKeyboardButton("🔄 Changer wallet", callback_data="wallet_change"),
                    InlineKeyboardButton("❌ Deconnecter", callback_data="wallet_disconnect"),
                ],
                [InlineKeyboardButton("⬅️ Menu principal", callback_data="menu_main")],
            ]
        )
        return text, reply_markup
