from __future__ import annotations

from datetime import datetime
from typing import Any


def format_execution_notification(signal: dict[str, Any], result: dict[str, Any], execution_mode: str, success: bool = True) -> str:
    status_emoji = "✅" if success else "❌"
    strategy = str(result.get("strategy") or "IMMEDIATE").upper()
    ticker = result.get("ticker") or signal.get("ticker") or signal.get("asset") or "Unknown"
    side = result.get("side") or signal.get("side") or signal.get("action") or "Unknown"
    requested_qty = float(result.get("requested_qty", result.get("requested_size", result.get("size", 0.0))) or 0.0)
    filled_qty = float(result.get("filled_qty", result.get("executed_size", result.get("total_filled_usd", 0.0))) or 0.0)
    execution_price = float(result.get("execution_price", result.get("price", result.get("target_price", 0.0))) or 0.0)
    notional_usd = float(result.get("notional_usd", result.get("total_filled_usd", filled_qty * execution_price)) or 0.0)
    price = float(result.get("price", result.get("target_price", 0.0)) or 0.0)

    lines = [
        f"{status_emoji} *Trade Executed*",
        f"• *Ticker* : `{ticker}`",
        f"• *Side* : `{side}`",
        f"• *Strategy* : `{strategy}`",
        f"• *Requested* : `{requested_qty:.2f}`",
        f"• *Filled* : `{filled_qty:.2f}` @ `{execution_price:.4f}`",
        f"• *Notional* : `{notional_usd:.2f} USDC`",
        f"• *Mode* : `{execution_mode}`",
    ]

    if strategy == "TWAP":
        slices_filled = int(result.get("slices_filled", 0))
        slices_attempted = int(result.get("slices_attempted", 0))
        realized_pr = float(result.get("realized_participation_rate", 0.0) or 0.0)
        capped_events = int(result.get("volume_capped_events", 0))
        avg_market_volume = float(result.get("avg_market_volume_observed", 0.0) or 0.0)
        true_completion_rate = float(result.get("true_completion_rate", 0.0) or 0.0)
        lines.extend(
            [
                f"• *Tranches* : `{slices_filled}/{slices_attempted}`",
                f"• *Completion Réelle* : `{true_completion_rate:.2%}`",
                f"• *PR Réalisé* : `{realized_pr:.2%}`",
                f"• *Volume Moyen Observé* : `{avg_market_volume:,.2f}`",
                f"• *Limitation Vol.* : `{capped_events}`",
            ]
        )

    if result.get("execution_preference") == "PASSIVE_ONLY":
        lines.append("• *Mode d'exécution* : `PASSIVE_ONLY`")

    if strategy == "TWAP" and int(result.get("volume_capped_events", 0)) > 0:
        lines.append("")
        lines.append("_L’exécution a été ralentie pour respecter le Participation Rate._")

    return "\n".join(lines)


def format_cognitive_decision_notification(decision: dict[str, Any], ticker: str = "Unknown") -> str:
    microstructure_regime = str(decision.get("microstructure_regime") or "UNKNOWN").upper()
    observed_liquidity_score = float(decision.get("observed_liquidity_score", 0.0) or 0.0)
    take_profit_bias = float(decision.get("take_profit_bias", 0.0) or 0.0)
    stop_loss_bias = float(decision.get("stop_loss_bias", 0.0) or 0.0)
    spread_bps = float(decision.get("spread_bps", 0.0) or 0.0)
    order_imbalance = float(decision.get("order_imbalance", 0.0) or 0.0)

    reason = str(decision.get("reason") or "No reason provided")
    lines = [
        "🧠 *Décision Lobstar Cognitive Brain*",
        f"• *Ticker* : `{ticker}`",
        f"• *Verdict* : `{decision.get('action', 'UNKNOWN')}`",
        f"• *Régime CLOB* : `{microstructure_regime}`",
        f"• *Score Liquidité* : `{observed_liquidity_score:.2f}/1.00`",
        f"• *Spread* : `{spread_bps:.2f} bps`",
        f"• *Order Imbalance* : `{order_imbalance:+.4f}`",
    ]

    if abs(take_profit_bias) > 0.0 or abs(stop_loss_bias) > 0.0:
        lines.extend(
            [
                "⚡ *Ajustements Microstructure* :",
                f"  └ TP Bias : `{take_profit_bias:+.2f} bps`",
                f"  └ SL Bias : `{stop_loss_bias:+.2f} bps`",
            ]
        )

    lines.append(f"• *Raison* : _{reason}_")
    return "\n".join(lines)


def format_daily_tca_report(summary: dict[str, Any], as_of_utc: datetime | None = None, metrics_path: str = "") -> str:
    global_summary = summary.get("global", {}) if isinstance(summary, dict) else {}
    assets_summary = summary.get("assets", {}) if isinstance(summary, dict) else {}
    as_of = as_of_utc or datetime.utcnow()

    total_orders = int(global_summary.get("total_orders", 0) or 0)
    total_volume = float(global_summary.get("total_volume_usd", 0.0) or 0.0)
    true_completion_rate = float(global_summary.get("true_completion_rate", 0.0) or 0.0)
    avg_slippage_bps = float(global_summary.get("avg_slippage_bps", 0.0) or 0.0)
    volume_capped_ratio = float(global_summary.get("volume_capped_ratio", 0.0) or 0.0)
    twap_orders = int(global_summary.get("twap_orders", 0) or 0)

    top_assets = sorted(
        assets_summary.items(),
        key=lambda item: float(item[1].get("total_volume_usd", 0.0) or 0.0),
        reverse=True,
    )[:3]

    lines = [
        "📊 *Daily TCA Report*",
        f"• *As of* : `{as_of.strftime('%Y-%m-%d %H:%M UTC')}`",
        f"• *Source* : `{metrics_path or 'execution_metrics.jsonl'}`",
        "──────────────",
        f"• *Total Orders* : `{total_orders}`",
        f"• *Total Volume* : `{total_volume:,.2f} USDC`",
        f"• *True Completion* : `{true_completion_rate:.2%}`",
        f"• *Avg Slippage* : `{avg_slippage_bps:+.2f} bps`",
        f"• *Volume Capped Ratio* : `{volume_capped_ratio:.2%}`",
        f"• *TWAP Orders* : `{twap_orders}`",
    ]

    if top_assets:
        lines.append("──────────────")
        lines.append("• *Top Assets*")
        for asset, data in top_assets:
            asset_volume = float(data.get("total_volume_usd", 0.0) or 0.0)
            asset_completion = float(data.get("true_completion_rate", 0.0) or 0.0)
            asset_slippage = float(data.get("avg_slippage_bps", 0.0) or 0.0)
            lines.append(
                f"  └ `{asset}`: `{asset_volume:,.2f} USDC` | `{asset_completion:.2%}` | `{asset_slippage:+.2f} bps`"
            )

    lines.append("──────────────")
    lines.append("_Generated from JSONL TCA metrics._")
    return "\n".join(lines)
