from typing import Optional
from services.portfolio_risk_engine import PortfolioRiskEngine
from database.ledger_db import Ledger
from strategies.risk_validation import EXECUTION_FRICTION
from utils.regime_utils import get_regime_label

def get_execution_tools(mcp, ledger: Optional[Ledger], risk: Optional[PortfolioRiskEngine], hmm=None):
    @mcp.tool(
        name="get_friction_model",
        description="Returns the current execution friction cost per contract used in backtest validation.",
    )
    def get_friction_model() -> dict:
        return {
            "friction_per_contract": EXECUTION_FRICTION,
            "description": "Fixed $0.005 penalty per binary contract action simulating CLOB slippage.",
        }

    @mcp.tool(
        name="lobstar_submit_signal",
        description="Bridge for LOBSTAR semantic agent: accepts a parsed signal dict and routes it through typing validation before execution.",
    )
    def lobstar_submit_signal(
        action: str,
        asset: str,
        side: str,
        size: float,
        price: float,
        confidence: float = 0.5,
    ) -> dict:
        if ledger is None:
            return {"error": "Ledger not initialized"}

        action_upper = action.upper().strip()
        side_upper = side.upper().strip()

        if action_upper not in ("BUY", "SELL", "HOLD"):
            return {"error": f"Invalid action: {action}"}
        if side_upper not in ("BUY", "SELL"):
            return {"error": f"Invalid side: {side}"}
        if size <= 0:
            return {"error": "Size must be positive"}
        if price <= 0:
            return {"error": "Price must be positive"}

        regime = get_regime_label(hmm, asset)

        if risk is not None:
            sizing = risk.compute_position_size(
                ticker=asset, side=side_upper, price=price,
                confidence=confidence, win_prob=confidence,
                regime_label=regime,
            )
            risk_size = sizing["size"]
        else:
            risk_size = size
            sizing = {"capital_at_risk": risk_size * price}

        if risk_size <= 0:
            return {"error": f"Risk engine blocked: zero size for {asset} ({regime})"}

        validation = ledger.validate_and_reserve(
            ticker=asset, side=side_upper, limit_price=price, requested_size=risk_size
        )
        if not validation["authorized"]:
            return {"error": validation["reason"], "authorized": False}

        position_id = f"{asset}-{side_upper}-{hash((asset, side_upper))}"
        ledger.record_order(
            position_id=position_id,
            ticker=asset,
            side=side_upper,
            price=price,
            size=validation["size"],
        )

        if risk is not None:
            risk.book_exposure(asset, validation["size"], side_upper)

        return {
            "authorized": True,
            "position_id": position_id,
            "size": validation["size"],
            "capital": validation["capital"],
            "reason": validation["reason"],
            "kelly_pct": sizing.get("kelly_pct", 0),
            "net_beta_exposure_pct": sizing.get("net_beta_exposure_pct", 0),
        }
