import os
from database.ledger_db import Ledger
from services.portfolio_risk_engine import PortfolioRiskEngine
from strategies.hmm_filter import HMMRegimeFilter

def calculate_kelly_size(
    ticker: str,
    side: str,
    price: float,
    confidence: float = 0.55,
    regime: str = "LOW_VOLATILITY"
) -> dict:
    """Calculates position size using the core risk engine."""
    # Use a sandboxed ledger to prevent db locks
    db_path = "user_data/data/skills_transient.db"
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    ledger = Ledger(db_path=db_path)
    # Ensure standard capital allocation is present
    cursor = ledger.conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO capital_allocation (id, total_capital, available_capital, allocated_pct) "
        "VALUES (1, 10000.0, 10000.0, 10.0)"
    )
    ledger.conn.commit()

    hmm = HMMRegimeFilter()
    risk = PortfolioRiskEngine(ledger=ledger, hmm_filter=hmm)

    sizing = risk.compute_position_size(
        ticker=ticker,
        side=side,
        price=price,
        confidence=confidence,
        regime_label=regime
    )

    return {
        "status": "SUCCESS",
        "ticker": ticker.upper(),
        "side": side.upper(),
        "price": price,
        "regime": regime,
        "recommended_size": sizing.get("size", 0.0),
        "capital_at_risk": sizing.get("capital_at_risk", 0.0),
        "kelly_pct": sizing.get("kelly_pct", 0.0)
    }
