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
        f"{status_emoji} <b>Trade Executed</b>",
        f"• <b>Ticker</b> : <code>{ticker}</code>",
        f"• <b>Side</b> : <code>{side}</code>",
        f"• <b>Strategy</b> : <code>{strategy}</code>",
        f"• <b>Requested</b> : <code>{requested_qty:.2f}</code>",
        f"• <b>Filled</b> : <code>{filled_qty:.2f}</code> @ <code>{execution_price:.4f}</code>",
        f"• <b>Notional</b> : <code>{notional_usd:.2f} USDC</code>",
        f"• <b>Mode</b> : <code>{execution_mode}</code>",
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
                f"• <b>Tranches</b> : <code>{slices_filled}/{slices_attempted}</code>",
                f"• <b>Completion Réelle</b> : <code>{true_completion_rate:.2%}</code>",
                f"• <b>PR Réalisé</b> : <code>{realized_pr:.2%}</code>",
                f"• <b>Volume Moyen Observé</b> : <code>{avg_market_volume:,.2f}</code>",
                f"• <b>Limitation Vol.</b> : <code>{capped_events}</code>",
            ]
        )

    if result.get("execution_preference") == "PASSIVE_ONLY":
        lines.append("• <b>Mode d'exécution</b> : <code>PASSIVE_ONLY</code>")

    if strategy == "TWAP" and int(result.get("volume_capped_events", 0)) > 0:
        lines.append("")
        lines.append("<i>L’exécution a été ralentie pour respecter le Participation Rate.</i>")

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
        "🧠 <b>Décision Lobstar Cognitive Brain</b>",
        f"• <b>Ticker</b> : <code>{ticker}</code>",
        f"• <b>Verdict</b> : <code>{decision.get('action', 'UNKNOWN')}</code>",
        f"• <b>Régime CLOB</b> : <code>{microstructure_regime}</code>",
        f"• <b>Score Liquidité</b> : <code>{observed_liquidity_score:.2f}/1.00</code>",
        f"• <b>Spread</b> : <code>{spread_bps:.2f} bps</code>",
        f"• <b>Order Imbalance</b> : <code>{order_imbalance:+.4f}</code>",
    ]

    if abs(take_profit_bias) > 0.0 or abs(stop_loss_bias) > 0.0:
        lines.extend(
            [
                "⚡ <b>Ajustements Microstructure</b> :",
                f"  └ TP Bias : <code>{take_profit_bias:+.2f} bps</code>",
                f"  └ SL Bias : <code>{stop_loss_bias:+.2f} bps</code>",
            ]
        )

    lines.append(f"• <b>Raison</b> : <i>{reason}</i>")
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
        "📊 <b>Daily TCA Report</b>",
        f"• <b>As of</b> : <code>{as_of.strftime('%Y-%m-%d %H:%M UTC')}</code>",
        f"• <b>Source</b> : <code>{metrics_path or 'execution_metrics.jsonl'}</code>",
        "──────────────",
        f"• <b>Total Orders</b> : <code>{total_orders}</code>",
        f"• <b>Total Volume</b> : <code>{total_volume:,.2f} USDC</code>",
        f"• <b>True Completion</b> : <code>{true_completion_rate:.2%}</code>",
        f"• <b>Avg Slippage</b> : <code>{avg_slippage_bps:+.2f} bps</code>",
        f"• <b>Volume Capped Ratio</b> : <code>{volume_capped_ratio:.2%}</code>",
        f"• <b>TWAP Orders</b> : <code>{twap_orders}</code>",
    ]

    if top_assets:
        lines.append("──────────────")
        lines.append("• <b>Top Assets</b>")
        for asset, data in top_assets:
            asset_volume = float(data.get("total_volume_usd", 0.0) or 0.0)
            asset_completion = float(data.get("true_completion_rate", 0.0) or 0.0)
            asset_slippage = float(data.get("avg_slippage_bps", 0.0) or 0.0)
            lines.append(
                f"  └ <code>{asset}</code>: <code>{asset_volume:,.2f} USDC</code> | <code>{asset_completion:.2%}</code> | <code>{asset_slippage:+.2f} bps</code>"
            )

    lines.append("──────────────")
    lines.append("<i>Generated from JSONL TCA metrics.</i>")
    return "\n".join(lines)
