from __future__ import annotations

from dataclasses import dataclass

from utils.config_loader import TRADING_PARAMS


@dataclass(frozen=True)
class TradeObjectiveEstimate:
    objective: str
    expected_gross_profit_usdc: float
    estimated_cost_usdc: float
    expected_net_profit_usdc: float
    estimated_fee_usdc: float
    estimated_spread_cost_usdc: float
    estimated_order_penalty_usdc: float
    estimated_cost_per_share: float


def estimate_trade_objective(
    *,
    edge: float,
    price: float,
    size: float,
    spread: float = 0.0,
    order_type: str = "LIMIT",
    fee_bps: float | None = None,
) -> TradeObjectiveEstimate:
    safe_price = max(0.0, float(price))
    safe_size = max(0.0, float(size))
    safe_edge = max(0.0, float(edge))
    safe_spread = max(0.0, float(spread))
    resolved_fee_bps = float(
        TRADING_PARAMS["ESTIMATED_TRADE_FEE_BPS"] if fee_bps is None else fee_bps
    )

    fee_rate = max(0.0, resolved_fee_bps) / 10_000.0
    estimated_fee_usdc = safe_size * safe_price * fee_rate * 2.0
    estimated_spread_cost_usdc = safe_size * safe_spread * 0.5
    order_penalty_per_share = 0.004 if str(order_type).upper() == "MARKET" else 0.001
    estimated_order_penalty_usdc = safe_size * order_penalty_per_share
    estimated_cost_usdc = (
        estimated_fee_usdc
        + estimated_spread_cost_usdc
        + estimated_order_penalty_usdc
    )
    expected_gross_profit_usdc = safe_edge * safe_size
    expected_net_profit_usdc = expected_gross_profit_usdc - estimated_cost_usdc
    estimated_cost_per_share = estimated_cost_usdc / safe_size if safe_size > 0 else 0.0

    return TradeObjectiveEstimate(
        objective=str(TRADING_PARAMS.get("OBJECTIVE", "maximize_polymarket_usdc")),
        expected_gross_profit_usdc=expected_gross_profit_usdc,
        estimated_cost_usdc=estimated_cost_usdc,
        expected_net_profit_usdc=expected_net_profit_usdc,
        estimated_fee_usdc=estimated_fee_usdc,
        estimated_spread_cost_usdc=estimated_spread_cost_usdc,
        estimated_order_penalty_usdc=estimated_order_penalty_usdc,
        estimated_cost_per_share=estimated_cost_per_share,
    )
