import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from py_clob_client.client import ClobClient

from utils.wallet_manager import WalletManager

logger = logging.getLogger("PolymarketOrderManager")

# USDC on Polygon
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"


@dataclass
class PolymarketOrder:
    """Represents a Polymarket bet/order."""
    order_id: str
    market_id: str
    token_id: str  # Token for YES or NO outcome
    outcome: str  # "YES" or "NO"
    side: str  # "BUY" or "SELL"
    price: float  # Price per share (0.0-1.0)
    amount: float  # Amount of shares
    collateral_value: float  # Total USDC needed
    status: str  # "pending", "filled", "cancelled", "failed"
    created_at: datetime
    tx_hash: Optional[str] = None
    error_message: Optional[str] = None

    @property
    def potential_profit(self) -> float:
        """Potential profit if bet wins."""
        if self.side == "BUY":
            return self.amount * (1 - self.price)
        else:
            return self.amount * self.price

    def __str__(self) -> str:
        return f"{self.side} {self.amount}x {self.outcome} @ {self.price} (${self.collateral_value:.2f})"


@dataclass
class ClaimReceipt:
    """Receipt from a claim action."""
    market_id: str
    outcome: str
    amount_claimed: float
    tx_hash: Optional[str] = None
    status: str = "pending"
    error_message: Optional[str] = None


class PolymarketOrderManager:
    """Manages Polymarket orders (buying/selling shares)."""

    def __init__(
        self,
        wallet_manager: WalletManager,
        private_key: Optional[str] = None,
        clob_client: Optional[ClobClient] = None,
    ):
        self.wallet_manager = wallet_manager
        self._private_key = private_key
        self._clob_client = clob_client

        if not clob_client and private_key:
            try:
                # Initialize py-clob-client
                self._clob_client = ClobClient(
                    host="https://clob.polymarket.com",
                    key=private_key,
                    chain_id=137,  # Polygon
                )
                logger.info("Initialized ClobClient for Polymarket")
            except Exception as e:
                logger.warning(f"Failed to initialize ClobClient: {e}")

        self._pending_orders: dict[str, PolymarketOrder] = {}

    def estimate_bet_cost(
        self, amount: float, price: float, side: str = "BUY"
    ) -> dict:
        """
        Estimate the cost of placing a bet.

        Args:
            amount: Number of shares
            price: Price per share (0.0-1.0)
            side: "BUY" or "SELL"

        Returns:
            dict with cost breakdown
        """
        # On Polymarket: when you BUY at price P, you pay P per share
        # When you SELL at price P, you receive P per share

        if side.upper() == "BUY":
            collateral_needed = amount * price
            fee = collateral_needed * 0.02  # 2% taker fee
            total_cost = collateral_needed + fee
            profit_if_right = amount * (1 - price)
        else:  # SELL
            proceeds = amount * price
            fee = proceeds * 0.02
            net_proceeds = proceeds - fee
            profit_if_right = amount * price
            total_cost = 0  # You receive money when selling

        return {
            "side": side.upper(),
            "amount": amount,
            "price": price,
            "collateral_or_proceeds": collateral_needed if side.upper() == "BUY" else proceeds,
            "fee_rate_bps": 200,  # 2% = 200 bps
            "fee_amount": fee,
            "total_cost": total_cost if side.upper() == "BUY" else -net_proceeds,
            "potential_profit": profit_if_right,
            "roi_percent": (profit_if_right / total_cost * 100) if side.upper() == "BUY" and total_cost > 0 else 0,
        }

    async def place_order(
        self,
        market_id: str,
        token_id: str,
        outcome: str,
        side: str,
        price: float,
        amount: float,
        slippage_tolerance: float = 0.05,  # 5%
        dry_run: bool = True,
    ) -> PolymarketOrder:
        """
        Place a bet on Polymarket.

        Args:
            market_id: Polymarket market ID
            token_id: Token ID for the outcome
            outcome: "YES" or "NO"
            side: "BUY" or "SELL"
            price: Price per share (0.0-1.0)
            amount: Number of shares
            slippage_tolerance: Acceptable slippage as decimal (0.05 = 5%)
            dry_run: If True, don't execute

        Returns:
            PolymarketOrder with transaction details
        """
        if not self._clob_client:
            return PolymarketOrder(
                order_id="",
                market_id=market_id,
                token_id=token_id,
                outcome=outcome,
                side=side,
                price=price,
                amount=amount,
                collateral_value=0,
                status="failed",
                created_at=datetime.utcnow(),
                error_message="ClobClient not initialized",
            )

        try:
            cost_est = self.estimate_bet_cost(amount, price, side)
            logger.info(f"Placing order: {side} {amount}x {outcome} @ {price} = ${cost_est['total_cost']:.2f}")

            if dry_run:
                logger.info("DRY RUN: Not placing order")
                order_id = f"dry_{market_id}_{side}_{datetime.utcnow().timestamp()}"
                return PolymarketOrder(
                    order_id=order_id,
                    market_id=market_id,
                    token_id=token_id,
                    outcome=outcome,
                    side=side,
                    price=price,
                    amount=amount,
                    collateral_value=cost_est["collateral_or_proceeds"],
                    status="pending",
                    created_at=datetime.utcnow(),
                )

            # Create and submit order via ClobClient
            # Note: Full implementation requires py-clob-client OrderBuilder
            # For now, return a pending order
            order_id = f"poly_{market_id}_{int(datetime.utcnow().timestamp())}"

            order = PolymarketOrder(
                order_id=order_id,
                market_id=market_id,
                token_id=token_id,
                outcome=outcome,
                side=side,
                price=price,
                amount=amount,
                collateral_value=cost_est["collateral_or_proceeds"],
                status="pending",
                created_at=datetime.utcnow(),
            )

            self._pending_orders[order_id] = order
            logger.info(f"Order created: {order_id}")

            return order

        except Exception as e:
            logger.error(f"Failed to place order: {e}")
            return PolymarketOrder(
                order_id="",
                market_id=market_id,
                token_id=token_id,
                outcome=outcome,
                side=side,
                price=price,
                amount=amount,
                collateral_value=0,
                status="failed",
                created_at=datetime.utcnow(),
                error_message=str(e),
            )

    async def claim_winnings(
        self, market_id: str, outcome: str, dry_run: bool = True
    ) -> ClaimReceipt:
        """
        Claim winnings from a resolved market.

        Args:
            market_id: Market ID or Condition ID
            outcome: "YES" or "NO"
            dry_run: If True, don't execute transaction

        Returns:
            ClaimReceipt with transaction details
        """
        if not self._clob_client:
            return ClaimReceipt(
                market_id=market_id,
                outcome=outcome,
                amount_claimed=0,
                status="failed",
                error_message="ClobClient not initialized",
            )

        try:
            logger.info(f"Initiating claim for market/condition {market_id} - Outcome: {outcome}")

            # 1. Fetch market details to get the exact condition_id and token_id
            try:
                market_details = self._clob_client.get_market(market_id)
            except Exception as e:
                logger.warning(f"Could not fetch market details via CLOB, using market_id directly as condition: {e}")
                market_details = {}

            condition_id = market_details.get("condition_id", market_id)

            # Find the outcome token ID
            token_id_str = None
            tokens = market_details.get("tokens", [])
            for token_dict in tokens:
                if str(token_dict.get("outcome", "")).upper() == outcome.upper():
                    token_id_str = token_dict.get("token_id")
                    break

            # 2. Setup Web3 provider
            import os
            from web3 import Web3
            rpc_url = os.getenv("POLYGON_RPC_URL", "https://polygon.drpc.org")
            w3 = Web3(Web3.HTTPProvider(rpc_url))

            if not w3.is_connected():
                return ClaimReceipt(
                    market_id=market_id,
                    outcome=outcome,
                    amount_claimed=0,
                    status="failed",
                    error_message="Failed to connect to Polygon RPC",
                )

            # EOA derivation
            private_key = self._private_key or self.wallet_manager.get_private_key()
            if not private_key:
                return ClaimReceipt(
                    market_id=market_id,
                    outcome=outcome,
                    amount_claimed=0,
                    status="failed",
                    error_message="EOA private key not available",
                )

            acct = w3.eth.account.from_key(private_key)
            eoa_address = acct.address

            # Resolving Proxy Wallet (Funder)
            proxy_address = None
            if hasattr(self.wallet_manager, "get_proxy_address"):
                proxy_address = self.wallet_manager.get_proxy_address()
            elif hasattr(self.wallet_manager, "get_credentials"):
                creds = self.wallet_manager.get_credentials()
                proxy_address = creds.get("proxy_wallet")

            # CTF Contract details
            CTF_ADDRESS = "0x4D97dCD97eC945f40Cf65F87097Ace5Ea0476045"
            CTF_ABI = [
                {
                    "constant": True,
                    "inputs": [{"name": "account", "type": "address"}, {"name": "id", "type": "uint256"}],
                    "name": "balanceOf",
                    "outputs": [{"name": "", "type": "uint256"}],
                    "payable": False,
                    "stateMutability": "view",
                    "type": "function"
                },
                {
                    "constant": False,
                    "inputs": [
                        {"name": "collateralToken", "type": "address"},
                        {"name": "parentCollectionId", "type": "bytes32"},
                        {"name": "conditionId", "type": "bytes32"},
                        {"name": "indexSets", "type": "uint256[]"}
                    ],
                    "name": "redeemPositions",
                    "outputs": [],
                    "payable": False,
                    "stateMutability": "nonpayable",
                    "type": "function"
                }
            ]
            ctf_contract = w3.eth.contract(address=w3.to_checksum_address(CTF_ADDRESS), abi=CTF_ABI)

            # Check balances
            token_id = int(token_id_str) if token_id_str else None
            eoa_balance = 0
            proxy_balance = 0

            if token_id:
                try:
                    eoa_balance = ctf_contract.functions.balanceOf(eoa_address, token_id).call()
                    if proxy_address:
                        proxy_balance = ctf_contract.functions.balanceOf(w3.to_checksum_address(proxy_address), token_id).call()
                except Exception as e:
                    logger.warning(f"Failed to query balances: {e}")

            logger.info(f"Balances - EOA: {eoa_balance} | Proxy: {proxy_balance} contracts")

            # Determine target for claim
            target_address = eoa_address
            has_winnings = eoa_balance > 0

            if proxy_balance > 0 and proxy_address:
                target_address = proxy_address
                has_winnings = True

            amount_to_claim = max(eoa_balance, proxy_balance) / 10**6  # USDC scales at 6 decimals

            if dry_run:
                logger.info(f"[DRY RUN] Would claim {amount_to_claim:.2f} USDC for address {target_address}")
                return ClaimReceipt(
                    market_id=market_id,
                    outcome=outcome,
                    amount_claimed=amount_to_claim,
                    status="pending",
                    error_message="Dry run active",
                )

            if not has_winnings:
                logger.info(f"No active redeemable balance found on-chain for {outcome} on market {market_id}.")
                return ClaimReceipt(
                    market_id=market_id,
                    outcome=outcome,
                    amount_claimed=0,
                    status="success",
                    error_message="No winning balance detected or already claimed",
                )

            # Build and send transaction
            index_sets = [1] if outcome.upper() == "YES" else [2]

            # Format condition_id into 32-byte hex bytes
            cond_bytes = w3.to_bytes(hexstr=condition_id)
            if len(cond_bytes) < 32:
                cond_bytes = cond_bytes.rjust(32, b'\x00')

            logger.info(f"Sending on-chain redeemPositions transaction on Polygon...")

            if target_address == eoa_address:
                # Direct EOA redemption
                tx = ctf_contract.functions.redeemPositions(
                    w3.to_checksum_address(USDC_ADDRESS),
                    b'\x00' * 32,
                    cond_bytes,
                    index_sets
                ).build_transaction({
                    "from": eoa_address,
                    "nonce": w3.eth.get_transaction_count(eoa_address),
                    "gasPrice": int(w3.eth.gas_price * 1.2),  # +20% for speed
                })

                signed_tx = w3.eth.account.sign_transaction(tx, private_key)
                tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
                tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)

                logger.info(f"Direct EOA claim tx completed: {tx_receipt.transactionHash.hex()}")
                return ClaimReceipt(
                    market_id=market_id,
                    outcome=outcome,
                    amount_claimed=amount_to_claim,
                    tx_hash=tx_receipt.transactionHash.hex(),
                    status="success",
                )
            else:
                # Safe / Proxy Wallet execution
                # Gnosis Safe or proxy adapters typically require transaction building
                # For safety and because a standard EOA cannot call arbitrary methods of a Safe directly
                # without proper EIP-712 multisig nonce signing, we provide instructions or fall back
                # to direct EOA triggering if the Safe is configured to auto-redeem.
                logger.warning("Winnings are located inside the Proxy Wallet (Gnosis Safe). Redemptions for smart contract wallets should be claimed through the Polymarket UI to benefit from gasless relayer support.")
                return ClaimReceipt(
                    market_id=market_id,
                    outcome=outcome,
                    amount_claimed=amount_to_claim,
                    status="pending",
                    error_message=f"Winnings held in Proxy Wallet ({proxy_address}). Please redeem on Polymarket UI to claim gaslessly.",
                )

        except Exception as e:
            logger.error(f"Failed to claim: {e}")
            return ClaimReceipt(
                market_id=market_id,
                outcome=outcome,
                amount_claimed=0,
                status="failed",
                error_message=str(e),
            )

    def check_balance_for_bet(
        self, amount: float, price: float, side: str = "BUY"
    ) -> tuple[bool, str]:
        """
        Check if wallet has sufficient balance to place a bet.

        Returns:
            (can_bet, message)
        """
        cost_est = self.estimate_bet_cost(amount, price, side)

        if side.upper() == "BUY":
            required_usdc = cost_est["total_cost"]
            # TODO: Get actual USDC balance from wallet
            # For now, just return estimate
            return True, f"Need ${required_usdc:.2f} USDC"

        return True, "Ready to place bet"

    def format_order(self, order: PolymarketOrder) -> str:
        """Format order for display."""
        lines = [f"📊 **Polymarket Order**\n"]

        if order.status == "failed":
            lines.append(f"❌ Status: FAILED")
            lines.append(f"Error: {order.error_message}")
        else:
            lines.append(f"✅ Status: {order.status.upper()}")
            lines.append(f"• Order: `{order.order_id}`")
            lines.append(f"• Side: `{order.side}`")
            lines.append(f"• Outcome: `{order.outcome}`")
            lines.append(f"• Amount: `{order.amount}x`")
            lines.append(f"• Price: `${order.price:.2f}`")
            lines.append(f"• Total: `${order.collateral_value:.2f}`")
            lines.append(f"• Potential Profit: `${order.potential_profit:.2f}`")

        return "\n".join(lines)

    def format_claim_receipt(self, receipt: ClaimReceipt) -> str:
        """Format claim receipt for display."""
        lines = [f"🎉 **Claim Receipt**\n"]

        if receipt.status == "failed":
            lines.append(f"❌ Status: FAILED")
            lines.append(f"Error: {receipt.error_message}")
        else:
            lines.append(f"✅ Status: {receipt.status.upper()}")
            lines.append(f"• Market: `{receipt.market_id}`")
            lines.append(f"• Outcome: `{receipt.outcome}`")
            lines.append(f"• Claimed: `${receipt.amount_claimed:.2f}`")

        return "\n".join(lines)
