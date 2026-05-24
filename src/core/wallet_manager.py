import logging
import asyncio
import re
import time
from html import escape
from collections import defaultdict
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
        self._allowance_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

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
                if proxy_address and proxy_address.lower() != wallet_address.lower():
                    proxy_pusd = await get_erc20_balance(self.pusd_contract, proxy_address)
                    proxy_usdc_native = await get_erc20_balance(self.usdc_native_contract, proxy_address)
                    proxy_usdc_e = await get_erc20_balance(self.usdc_polygon_contract, proxy_address)
                elif proxy_address and proxy_address.lower() == wallet_address.lower():
                    # If same address, just fetch pUSD as it wasn't counted in direct USDC
                    proxy_pusd = await get_erc20_balance(self.pusd_contract, wallet_address)
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

    async def get_erc20_allowance(self, token_contract: str, owner_address: str, spender_address: str) -> float:
        if not self.rpc_url:
            return 0.0
        payload = {
            "jsonrpc": "2.0",
            "method": "eth_call",
            "params": [
                {
                    "to": token_contract,
                    "data": f"0xdd62ed3e{owner_address.lower().replace('0x', '').zfill(64)}{spender_address.lower().replace('0x', '').zfill(64)}",
                },
                "latest",
            ],
            "id": 5,
        }
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(self.rpc_url, json=payload)
                result = resp.json().get("result", "0x0")
                return int(result, 16) / 1e6
        except Exception:
            return 0.0

    async def approve_usdc(self, private_key: str, spender_address: str, amount: float = 1_000_000.0) -> str:
        """Approuve une grosse somme d'USDC pour éviter les re-approuves fréquents."""
        from web3 import Web3
        w3 = Web3(Web3.HTTPProvider(self.rpc_url))
        account = Account.from_key(private_key)

        # ERC20 Approve ABI subset
        abi = [{"constant": False, "inputs": [{"name": "spender", "type": "address"}, {"name": "value", "type": "uint256"}], "name": "approve", "outputs": [{"name": "", "type": "bool"}], "payable": False, "stateMutability": "nonpayable", "type": "function"}]
        contract = w3.eth.contract(address=w3.to_checksum_address(self.usdc_native_contract), abi=abi)

        raw_amount = int(amount * 1e6)
        tx_params: dict[str, Any] = {
            "from": account.address,
            "nonce": w3.eth.get_transaction_count(account.address),
        }
        try:
            latest_block = w3.eth.get_block("latest")
            base_fee = int(getattr(latest_block, "baseFeePerGas", 0) or 0)
            priority_fee = int(w3.eth.max_priority_fee)
            if base_fee > 0 and priority_fee > 0:
                tx_params["maxFeePerGas"] = int(base_fee * 2 + priority_fee)
                tx_params["maxPriorityFeePerGas"] = int(priority_fee)
            else:
                tx_params["gasPrice"] = int(w3.eth.gas_price * 1.2)
        except Exception:
            tx_params["gasPrice"] = int(w3.eth.gas_price * 1.2)

        tx = contract.functions.approve(w3.to_checksum_address(spender_address), raw_amount).build_transaction(tx_params)
        signed_tx = account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        logger.info(f"USDC Approval tx sent: {tx_hash.hex()}")
        return tx_hash.hex()

    async def ensure_usdc_allowance(
        self,
        private_key: str,
        spender_address: str,
        required_amount: float,
        owner_address: str | None = None,
        approval_buffer_multiplier: float = 10.0,
        approval_min_buffer_usdc: float = 100.0,
        wait_timeout_seconds: float = 180.0,
        post_receipt_retry_count: int = 5,
        post_receipt_retry_delay_seconds: float = 1.0,
    ) -> dict[str, Any]:
        """Lazy allowance check: approve only when the remaining allowance is insufficient."""
        if required_amount <= 0:
            return {"approved": False, "reason": "Invalid required amount"}
        if not self.rpc_url:
            return {"approved": False, "reason": "RPC URL unavailable"}
        if not spender_address:
            return {"approved": False, "reason": "Spender address missing"}

        if not owner_address:
            from eth_account import Account
            owner_address = Account.from_key(private_key).address

        lock_key = f"{owner_address.lower()}::{spender_address.lower()}"
        async with self._allowance_locks[lock_key]:
            current_allowance = await self.get_erc20_allowance(
                self.usdc_native_contract,
                owner_address,
                spender_address,
            )
            if current_allowance >= required_amount:
                return {
                    "approved": True,
                    "action": "noop",
                    "allowance": current_allowance,
                    "required_amount": required_amount,
                }

            approval_amount = max(
                required_amount * approval_buffer_multiplier,
                required_amount + approval_min_buffer_usdc,
            )
            tx_hash = await self.approve_usdc(private_key, spender_address, amount=approval_amount)

            from web3 import Web3

            w3 = Web3(Web3.HTTPProvider(self.rpc_url))
            try:
                receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=wait_timeout_seconds)
            except Exception as exc:
                logger.warning("USDC approval wait failed or timed out: %s", exc)
                return {
                    "approved": False,
                    "action": "approve_timeout",
                    "tx_hash": tx_hash,
                    "allowance": current_allowance,
                    "required_amount": required_amount,
                }
            if getattr(receipt, "status", 0) != 1:
                return {
                    "approved": False,
                    "action": "approve_failed",
                    "tx_hash": tx_hash,
                    "allowance": current_allowance,
                    "required_amount": required_amount,
                }

            updated_allowance = current_allowance
            for attempt in range(max(1, int(post_receipt_retry_count))):
                updated_allowance = await self.get_erc20_allowance(
                    self.usdc_native_contract,
                    owner_address,
                    spender_address,
                )
                if updated_allowance >= required_amount:
                    break
                if attempt < max(1, int(post_receipt_retry_count)) - 1:
                    await asyncio.sleep(max(0.0, float(post_receipt_retry_delay_seconds)))
            return {
                "approved": True,
                "action": "approved" if updated_allowance >= required_amount else "approved_unverified",
                "tx_hash": tx_hash,
                "allowance": updated_allowance,
                "required_amount": required_amount,
                "approval_amount": approval_amount,
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
        Génère le texte en HTML pour un rendu stable sur mobile.
        """
        usdc_direct = float(soldes.get('usdc_direct', 0.0))
        usdc_proxy = float(soldes.get('usdc_proxy', 0.0))
        total_capital = usdc_direct + usdc_proxy
        safe_wallet_name = escape(str(wallet_name or "default"))
        safe_wallet_address = escape(str(wallet_address or "unavailable"))
        safe_proxy_address = escape(str(proxy_address or ""))

        lines = [
            "<b>🎯 Polymarket Cockpit</b>",
            "───────────────────",
            f"🟢 <b>Status</b>: <code>Connected</code>",
            f"🔑 <b>Wallet</b>: <code>{safe_wallet_name}</code>",
            f"📬 <b>Address</b>: <code>{safe_wallet_address}</code>"
        ]

        if proxy_address:
            lines.append(f"🛡️ <b>Proxy Wallet</b>: <code>{safe_proxy_address}</code>")

        lines.extend([
            "",
            f"💵 <b>USDC (Direct)</b>: <code>{usdc_direct:.2f}</code>",
            f"🛡️ <b>pUSD (Polymarket)</b>: <code>{usdc_proxy:.2f}</code>",
            f"💰 <b>Total Balance</b>: <b>{total_capital:.2f} $</b>",
            f"👛 <b>Gas (POL)</b>: <code>{float(soldes.get('eth_balance', 0.0)):.4f}</code>",
            "───────────────────"
        ])

        if not proxy_address:
            lines.append("💡 <i>Hint: Use <code>/import</code> or check your EOA-Proxy link to enable full pUSD tracking.</i>")
            lines.append("───────────────────")

        text = "\n".join(lines)

        keyboard = [
            [
                InlineKeyboardButton("🔄 Refresh", callback_data="wallet_refresh"),
                InlineKeyboardButton("📊 Positions", callback_data="wallet_positions"),
            ],
            [
                InlineKeyboardButton("📜 History", callback_data="wallet_history"),
                InlineKeyboardButton("💰 PnL", callback_data="wallet_pnl"),
            ],
            [
                InlineKeyboardButton("📋 Orders", callback_data="wallet_orders"),
                InlineKeyboardButton("⚙️ Settings", callback_data="wallet_settings"),
            ],
            [InlineKeyboardButton("⬅️ Return to Main Menu", callback_data="menu_main")],
        ]

        return text, InlineKeyboardMarkup(keyboard)

    def generer_settings_layout(self) -> Tuple[str, InlineKeyboardMarkup]:
        """Menu secondaire pour les actions sensibles/avancées."""
        text = (
            "<b>⚙️ WALLET SETTINGS</b>\n"
            "───────────────────\n"
            "Actions sensibles et configuration avancée."
        )
        keyboard = [
            [
                InlineKeyboardButton("🔑 Show Private Key", callback_data="wallet_show_key"),
                InlineKeyboardButton("🔀 Switch Wallet", callback_data="wallet_change"),
            ],
            [
                InlineKeyboardButton("❌ Disconnect", callback_data="wallet_disconnect"),
                InlineKeyboardButton("⬅️ Back", callback_data="wallet_refresh"),
            ]
        ]
        return text, InlineKeyboardMarkup(keyboard)
