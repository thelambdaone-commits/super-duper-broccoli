import logging
from datetime import datetime
import re
from typing import Dict, Any, Tuple

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
        self.usdc_polygon_contract = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # Bridged USDC.e
        self.usdc_native_contract = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"   # Native USDC
        self.pusd_contract = "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb"          # Polymarket V2 pUSD Collateral

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

    async def recuperer_soldes_on_chain(self, wallet_address: str, proxy_address: str = "") -> Dict[str, float]:
        if not self.rpc_url:
            return {
                "usdc_balance": 0.0,
                "usdc_direct": 0.0,
                "usdc_proxy": 0.0,
                "eth_balance": 0.0
            }

        eth_balance = 0.0
        
        # EOA Direct Balances
        eoa_usdc_native = 0.0
        eoa_usdc_e = 0.0
        
        # Proxy Balances
        proxy_pusd = 0.0
        proxy_usdc_native = 0.0
        proxy_usdc_e = 0.0

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                # 1. POL (gas) balance of EOA (wallet_address)
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

                # Helper to fetch ERC20 balance
                async def get_erc20_balance(token_contract: str, target_address: str) -> float:
                    if not target_address:
                        return 0.0
                    normalized = target_address.lower().replace("0x", "")
                    payload = {
                        "jsonrpc": "2.0",
                        "method": "eth_call",
                        "params": [
                            {
                                "to": token_contract,
                                "data": f"0x70a08231{normalized.zfill(64)}",
                            },
                            "latest",
                        ],
                        "id": 4,
                    }
                    try:
                        resp = await client.post(self.rpc_url, json=payload)
                        resp.raise_for_status()
                        result = resp.json().get("result", "0x0")
                        return int(result, 16) / 1e6
                    except Exception:
                        return 0.0

                # Query EOA balances
                eoa_usdc_native = await get_erc20_balance(self.usdc_native_contract, wallet_address)
                eoa_usdc_e = await get_erc20_balance(self.usdc_polygon_contract, wallet_address)

                # Query Proxy balances
                if proxy_address:
                    proxy_pusd = await get_erc20_balance(self.pusd_contract, proxy_address)
                    proxy_usdc_native = await get_erc20_balance(self.usdc_native_contract, proxy_address)
                    proxy_usdc_e = await get_erc20_balance(self.usdc_polygon_contract, proxy_address)
                else:
                    # Fallback to EOA if no proxy is configured
                    proxy_pusd = await get_erc20_balance(self.pusd_contract, wallet_address)

        except Exception as exc:
            logger.debug("Wallet balance RPC lookup failed: %s", exc)

        # Direct USDC = EOA native USDC + EOA USDC.e
        usdc_direct = eoa_usdc_native + eoa_usdc_e
        
        # Proxy Polymarket balance = Proxy pUSD + Proxy native USDC + Proxy USDC.e
        usdc_proxy = proxy_pusd + proxy_usdc_native + proxy_usdc_e

        return {
            "usdc_balance": float(usdc_direct + usdc_proxy),
            "usdc_direct": float(usdc_direct),
            "usdc_proxy": float(usdc_proxy),
            "eth_balance": float(eth_balance)
        }

    def generer_layout_telegram(
        self,
        wallet_name: str,
        wallet_address: str,
        soldes: Dict[str, Any],
        total_connections: int,
        proxy_address: str = "",
    ) -> Tuple[str, InlineKeyboardMarkup]:
        """
        Génère le texte en Markdown V1 sans échappement parasite pour un rendu parfait.
        """
        # Somme du capital (USDC direct + pUSD sur le Proxy de marché)
        usdc_direct = float(soldes.get('usdc_direct', 0.0))
        usdc_proxy = float(soldes.get('usdc_proxy', 0.0))
        total_capital = usdc_direct + usdc_proxy
        
        lines = [
            "🎯 *Polymarket Cockpit*",
            "────────────────────────",
            "🟢 *Status* : `Connected`",
            f"🔑 *Active Wallet* : `{wallet_name}`",
            f"📬 *EOA Address* : `{wallet_address}`"
        ]
        
        if proxy_address:
            lines.append(f"🛡️ *Proxy Address* : `{proxy_address}`")
            
        lines.extend([
            f"💵 *USDC Direct* : `{usdc_direct:.2f} USDC`",
            f"🛡️ *Polymarket pUSD* : `{usdc_proxy:.2f} pUSD`",
            f"💰 *Total Capital* : `{total_capital:.2f} $`",
            f"👛 *Gas Assets* : `{float(soldes.get('eth_balance', 0.0)):.4f} POL`",
            f"💾 *Saved Vaults* : `{total_connections}`",
            "────────────────────────"
        ])
        
        if not proxy_address:
            lines.append("⚠️ *No Proxy Wallet set.*")
            lines.append("Use `/wallet set-proxy <address>` in DM to track your Polymarket pUSD balance!")
            lines.append("────────────────────────")
            
        text = "\n".join(lines)
        
        # Clavier ultra-réactif avec gestionnaire de callback centralisé
        reply_markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("📜 History", callback_data="wallet_history"),
                    InlineKeyboardButton("📋 Active Orders", callback_data="wallet_orders"),
                ],
                [
                    InlineKeyboardButton("📊 Open Positions", callback_data="wallet_positions"),
                    InlineKeyboardButton("💰 PnL Metrics", callback_data="wallet_pnl"),
                ],
                [
                    InlineKeyboardButton("🔄 Refresh Balances", callback_data="wallet_refresh"),
                    InlineKeyboardButton("🔑 Export Private Key", callback_data="wallet_show_key"),
                ],
                [
                    InlineKeyboardButton("🔀 Switch Wallet", callback_data="wallet_change"),
                    InlineKeyboardButton("❌ Disconnect", callback_data="wallet_disconnect"),
                ],
                [InlineKeyboardButton("⬅️ Return to Main Menu", callback_data="menu_main")],
            ]
        )
        
        return text, reply_markup
