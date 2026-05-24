import logging
from decimal import Decimal

from database.ledger_db import Ledger

logger = logging.getLogger("OrderManager")


class OrderManager:
    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger

    def validate_and_execute(
        self,
        position_id: str,
        ticker: str,
        side: str,
        size: Decimal,
        price: Decimal,
    ) -> bool:
        validation = self.ledger.validate_and_reserve(
            ticker=ticker,
            side=side,
            limit_price=float(price),
            requested_size=float(size),
        )
        if not validation["authorized"]:
            logger.warning(f"Blocked {position_id} — {validation['reason']}")
            return False

        self.ledger.record_order(
            position_id=position_id,
            ticker=ticker,
            side=side,
            price=float(price),
            size=validation["size"],
        )
        return True

    def calibrate_size_for_liquidity(
        self,
        desired_size: Decimal,
        bid_liquidity: Decimal,
        ask_liquidity: Decimal,
        side: str,
        max_slippage_pct: Decimal = Decimal("0.01"),
    ) -> Decimal:
        available = bid_liquidity if side == "SELL" else ask_liquidity
        max_size = available * (Decimal("1") - max_slippage_pct)
        return min(desired_size, max_size)
