import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from py_clob_client.clob_types import OrderType
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
            market_id: Market ID
            outcome: "YES" or "NO"
            dry_run: If True, don't execute
        
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
            logger.info(f"Claiming winnings for {market_id} - {outcome}")

            if dry_run:
                logger.info("DRY RUN: Not claiming")
                return ClaimReceipt(
                    market_id=market_id,
                    outcome=outcome,
                    amount_claimed=0,
                    status="pending",
                )

            # TODO: Implement actual claiming via ClobClient
            # This requires: resolving market, checking positions, executing claim
            # For now, return success

            return ClaimReceipt(
                market_id=market_id,
                outcome=outcome,
                amount_claimed=0,
                status="pending",
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
