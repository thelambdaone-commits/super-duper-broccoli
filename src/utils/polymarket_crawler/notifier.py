from typing import Any


def format_signal_summary(signals: list[dict[str, Any]], decisions_data: dict[str, Any]) -> dict[str, Any]:
    active_decisions = [
        d for d in decisions_data.get("decisions", [])
        if float(d.get("allocation_usdc", 0) or 0) > 0.01
    ]
    total_alloc = sum(float(d.get("allocation_usdc", 0) or 0) for d in active_decisions)

    return {
        "total_signals": len(signals),
        "active_decisions": len(active_decisions),
        "total_allocation_usdc": round(total_alloc, 2),
        "top_wallets": [
            {
                "address": s.get("wallet", ""),
                "name": s.get("name", "unknown"),
                "score": s.get("overall_score", 0),
                "pnl": s.get("total_pnl", 0),
            }
            for s in signals[:5]
        ],
    }
