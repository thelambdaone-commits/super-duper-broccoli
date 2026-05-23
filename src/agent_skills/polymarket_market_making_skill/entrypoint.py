import math

def calculate_market_making_spreads(
    mid_price: float,
    volatility: float = 0.02,
    inventory: int = 0,
    target_inventory: int = 0
) -> dict:
    """
    Computes bid/ask price quotes using a customized Avellaneda-Stoikov model
    adapted for binary outcomes and prediction CLOB interfaces.
    """
    # Parameters
    gamma = 0.15          # Risk aversion parameter
    kappa = 1.5           # Order book liquidity density

    # Calculate inventory deviation
    inventory_delta = inventory - target_inventory

    # 1. Compute Reservation Price (Adjusted for inventory risk)
    # r = s - delta_inventory * gamma * vol^2
    reservation_price = mid_price - (inventory_delta * gamma * (volatility ** 2))

    # 2. Compute Optimal Spread Width
    # w = gamma * vol^2 + (2 / gamma) * ln(1 + gamma / kappa)
    ln_term = math.log(1.0 + (gamma / kappa))
    spread = (gamma * (volatility ** 2)) + ((2.0 / gamma) * ln_term)

    # Force a minimum spread of $0.01 (1 cent) and scale with volatility
    spread = max(0.01, spread, volatility * 0.5)

    # 3. Calculate Bid / Ask Quotes
    bid = reservation_price - (spread / 2.0)
    ask = reservation_price + (spread / 2.0)

    # Boundary constraints for Polymarket YES/NO prices ($0.01 to $0.99)
    bid = max(0.01, min(0.99, round(bid, 4)))
    ask = max(0.01, min(0.99, round(ask, 4)))

    # Prevent crossing bids/asks
    if bid >= ask:
        bid = max(0.01, round(mid_price - 0.005, 4))
        ask = min(0.99, round(mid_price + 0.005, 4))

    return {
        "status": "SUCCESS",
        "mid_price": mid_price,
        "reservation_price": round(reservation_price, 4),
        "spread_width": round(spread, 4),
        "bid_quote": bid,
        "ask_quote": ask,
        "inventory_delta": inventory_delta,
        "skew_direction": "NEUTRAL" if inventory_delta == 0 else ("SHORT_SKEWED" if inventory_delta > 0 else "LONG_SKEWED")
    }
