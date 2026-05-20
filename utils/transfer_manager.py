import logging
from dataclasses import dataclass
from typing import Optional

from eth_account import Account

try:
    from web3 import Web3
    from web3.exceptions import Web3ValidationError
    WEB3_AVAILABLE = True
except ImportError:
    WEB3_AVAILABLE = False
    Web3 = None
    Web3ValidationError = Exception

from utils.rpc_provider import resolve_rpc_with_fallback
from utils.wallet_manager import WalletManager, POLYGON_TOKENS

logger = logging.getLogger("TransferManager")

# ERC20 approve + transfer ABI
ERC20_TRANSFER_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "value", "type": "uint256"},
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"name": "spender", "type": "address"},
            {"name": "value", "type": "uint256"},
        ],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function",
    },
]


@dataclass
class TransferReceipt:
    """Receipt from a transfer transaction."""
    token: str
    from_address: str
    to_address: str
    amount: float
    raw_amount: int
    tx_hash: str
    status: str  # "success", "pending", "failed"
    gas_used: Optional[int] = None
    gas_price_gwei: Optional[float] = None
    error_message: Optional[str] = None

    @property
    def tx_url(self) -> str:
        return f"https://polygonscan.com/tx/{self.tx_hash}"


class TransferManager:
    """Manages token transfers on Polygon with fee calculation."""

    def __init__(
        self,
        wallet_manager: WalletManager,
        private_key: Optional[str] = None,
        polygon_rpc_url: Optional[str] = None,
    ):
        if not WEB3_AVAILABLE:
            raise ImportError("web3 is required for TransferManager. Install it with: pip install web3")
        
        self.wallet_manager = wallet_manager
        self.rpc_url = polygon_rpc_url or resolve_rpc_with_fallback("polygon")
        self.w3 = wallet_manager.w3
        self._private_key = private_key

        if not self.w3.is_connected():
            raise ValueError("Web3 not connected. Check RPC URL.")

        self._account = None
        self._from_address = None
        if private_key:
            try:
                self._account = Account.from_key(private_key)
                self._from_address = self._account.address
                logger.info(f"Loaded account: {self._from_address}")
            except Exception as e:
                logger.error(f"Failed to load private key: {e}")
                raise

    def estimate_gas_for_transfer(
        self, from_addr: str, to_addr: str, token: str, amount: float
    ) -> dict:
        """Estimate gas cost for a transfer."""
        try:
            token_upper = token.upper()
            if token_upper not in POLYGON_TOKENS:
                return {"error": f"Unknown token {token}"}

            from_checksum = Web3.to_checksum_address(from_addr)
            to_checksum = Web3.to_checksum_address(to_addr)

            if token_upper == "MATIC":
                # Native transfer
                gas_estimate = self.w3.eth.estimate_gas(
                    {"from": from_checksum, "to": to_checksum, "value": self.w3.to_wei(amount, "ether")}
                )
                return {
                    "gas_estimate": gas_estimate,
                    "avg_gas_price_gwei": float(self.w3.from_wei(self.w3.eth.gas_price, "gwei")),
                    "estimated_gas_cost_gwei": gas_estimate * float(self.w3.from_wei(self.w3.eth.gas_price, "gwei")) / 1e9,
                }
            else:
                # ERC20 transfer
                contract = self.w3.eth.contract(
                    address=Web3.to_checksum_address(POLYGON_TOKENS[token_upper]),
                    abi=ERC20_TRANSFER_ABI,
                )
                decimals = self.wallet_manager._token_decimals.get(token_upper, 6)
                raw_amount = int(amount * (10 ** decimals))

                # Build transaction for gas estimate
                tx = contract.functions.transfer(to_checksum, raw_amount).build_transaction(
                    {
                        "from": from_checksum,
                        "nonce": self.w3.eth.get_transaction_count(from_checksum),
                        "gasPrice": self.w3.eth.gas_price,
                    }
                )
                gas_estimate = self.w3.eth.estimate_gas(tx)
                gas_price = self.w3.eth.gas_price

                return {
                    "gas_estimate": gas_estimate,
                    "avg_gas_price_gwei": float(self.w3.from_wei(gas_price, "gwei")),
                    "estimated_gas_cost_gwei": float(self.w3.from_wei(gas_estimate * gas_price, "gwei")),
                }
        except Exception as e:
            logger.error(f"Gas estimation failed: {e}")
            return {"error": str(e)}

    async def transfer_tokens(
        self,
        to_address: str,
        token: str,
        amount: float,
        dry_run: bool = True,
    ) -> TransferReceipt:
        """
        Transfer tokens to an address.

        Args:
            to_address: Destination address
            token: Token name (e.g., "USDC", "POL", "MATIC")
            amount: Amount in human-readable form
            dry_run: If True, don't actually send the transaction

        Returns:
            TransferReceipt with transaction details
        """
        if not self._account or not self._from_address:
            return TransferReceipt(
                token=token,
                from_address="",
                to_address=to_address,
                amount=amount,
                raw_amount=0,
                tx_hash="",
                status="failed",
                error_message="No private key configured",
            )

        try:
            to_checksum = Web3.to_checksum_address(to_address)
            token_upper = token.upper()

            if token_upper not in POLYGON_TOKENS:
                raise ValueError(f"Unknown token {token}")

            # Get gas estimate
            gas_est = self.estimate_gas_for_transfer(
                self._from_address, to_address, token, amount
            )
            if "error" in gas_est:
                raise ValueError(gas_est["error"])

            # Build transaction
            nonce = self.w3.eth.get_transaction_count(self._from_address)
            gas_price = self.w3.eth.gas_price

            if token_upper == "MATIC":
                # Native transfer
                tx_dict = {
                    "from": self._from_address,
                    "to": to_checksum,
                    "value": self.w3.to_wei(amount, "ether"),
                    "nonce": nonce,
                    "gas": gas_est["gas_estimate"],
                    "gasPrice": gas_price,
                }
                raw_amount = self.w3.to_wei(amount, "ether")
            else:
                # ERC20 transfer
                contract = self.w3.eth.contract(
                    address=Web3.to_checksum_address(POLYGON_TOKENS[token_upper]),
                    abi=ERC20_TRANSFER_ABI,
                )
                decimals = self.wallet_manager._token_decimals.get(token_upper, 6)
                raw_amount = int(amount * (10 ** decimals))

                tx_dict = contract.functions.transfer(to_checksum, raw_amount).build_transaction(
                    {
                        "from": self._from_address,
                        "nonce": nonce,
                        "gas": gas_est["gas_estimate"],
                        "gasPrice": gas_price,
                    }
                )

            logger.info(f"Transfer TX: {token} {amount} to {to_checksum[:6]}...{to_checksum[-4:]}")
            logger.debug(f"Gas: {gas_est['gas_estimate']}, Price: {gas_est['avg_gas_price_gwei']} GWEI")

            if dry_run:
                logger.info("DRY RUN: Not sending transaction")
                return TransferReceipt(
                    token=token_upper,
                    from_address=self._from_address,
                    to_address=to_checksum,
                    amount=amount,
                    raw_amount=raw_amount,
                    tx_hash="0x0000000000000000000000000000000000000000000000000000000000000000",
                    status="pending",
                    gas_used=gas_est["gas_estimate"],
                    gas_price_gwei=gas_est["avg_gas_price_gwei"],
                )

            # Sign and send transaction
            signed_tx = self.w3.eth.account.sign_transaction(tx_dict, self._private_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)

            logger.info(f"Transaction sent: {tx_hash.hex()}")

            return TransferReceipt(
                token=token_upper,
                from_address=self._from_address,
                to_address=to_checksum,
                amount=amount,
                raw_amount=raw_amount,
                tx_hash=tx_hash.hex(),
                status="pending",
                gas_used=gas_est["gas_estimate"],
                gas_price_gwei=gas_est["avg_gas_price_gwei"],
            )

        except Web3ValidationError as e:
            logger.error(f"Validation error in transfer: {e}")
            return TransferReceipt(
                token=token,
                from_address=self._from_address or "",
                to_address=to_address,
                amount=amount,
                raw_amount=0,
                tx_hash="",
                status="failed",
                error_message=f"Invalid address: {e}",
            )
        except Exception as e:
            logger.error(f"Transfer failed: {e}")
            return TransferReceipt(
                token=token,
                from_address=self._from_address or "",
                to_address=to_address,
                amount=amount,
                raw_amount=0,
                tx_hash="",
                status="failed",
                error_message=str(e),
            )

    async def transfer_to_proxy_wallet(
        self,
        proxy_wallet_address: str,
        token: str,
        amount: float,
        dry_run: bool = True,
    ) -> TransferReceipt:
        """Transfer tokens to a proxy wallet."""
        return await self.transfer_tokens(proxy_wallet_address, token, amount, dry_run)

    def format_transfer_receipt(self, receipt: TransferReceipt) -> str:
        """Format a transfer receipt for display."""
        lines = [f"📤 **Transfer Receipt**\n"]

        if receipt.status == "failed":
            lines.append(f"❌ Status: FAILED")
            lines.append(f"Error: {receipt.error_message}")
        else:
            lines.append(f"✅ Status: {receipt.status.upper()}")
            lines.append(f"• Token: `{receipt.token}`")
            lines.append(f"• Amount: `{receipt.amount}`")
            lines.append(f"• From: `{receipt.from_address[:6]}...{receipt.from_address[-4:]}`")
            lines.append(f"• To: `{receipt.to_address[:6]}...{receipt.to_address[-4:]}`")

            if receipt.gas_used:
                lines.append(f"• Gas Used: `{receipt.gas_used}`")
            if receipt.gas_price_gwei:
                lines.append(f"• Gas Price: `{receipt.gas_price_gwei:.2f} GWEI`")

            lines.append(f"• TX: [{receipt.tx_hash[:10]}...](https://polygonscan.com/tx/{receipt.tx_hash})")

        return "\n".join(lines)
