from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from typing import Any

logger = logging.getLogger("PerformanceAnalyzer")


class PerformanceAnalyzer:
    def __init__(self, metrics_log_path: str = "data/execution_metrics.jsonl") -> None:
        self.metrics_log_path = metrics_log_path

    def generate_summary(self) -> dict[str, Any]:
        if not os.path.exists(self.metrics_log_path):
            return {"error": "No metrics file found yet."}

        stats_by_asset = defaultdict(
            lambda: {
                "total_orders": 0,
                "total_volume_usd": 0.0,
                "twap_orders": 0,
                "total_slices_attempted": 0,
                "total_slices_filled": 0,
                "total_capped_events": 0,
                "weighted_pr_sum": 0.0,
                "weighted_order_size_sum": 0.0,
                "weighted_spread_sum": 0.0,
                "requested_qty_sum": 0.0,
                "filled_qty_sum": 0.0,
            }
        )

        global_stats = {
            "total_orders": 0,
            "total_volume_usd": 0.0,
            "twap_orders": 0,
            "total_capped_events": 0,
            "total_slices_attempted": 0,
            "total_slices_filled": 0,
            "weighted_pr_sum": 0.0,
            "weighted_order_size_sum": 0.0,
            "weighted_spread_sum": 0.0,
            "requested_qty_sum": 0.0,
            "filled_qty_sum": 0.0,
        }

        with open(self.metrics_log_path, "r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("Skipping malformed JSONL line in %s", self.metrics_log_path)
                    continue

                asset = str(data.get("asset", "UNKNOWN"))
                requested_qty = float(data.get("requested_qty", data.get("size_usd", 0.0)) or 0.0)
                filled_qty = float(data.get("filled_qty", data.get("executed_size_usd", 0.0)) or 0.0)
                execution_price = float(data.get("execution_price", data.get("target_price", data.get("price", 0.0))) or 0.0)
                notional_usd = float(data.get("notional_usd", data.get("total_filled_usd", data.get("executed_size_usd", 0.0))) or 0.0)
                size = notional_usd
                strat = str(data.get("strategy", "IMMEDIATE")).upper()
                avg_market_volume = float(data.get("avg_market_volume_observed", 0.0) or 0.0)
                realized_pr = float(data.get("realized_participation_rate", 0.0) or 0.0)
                slices_attempted = int(data.get("slices_attempted", 0) or 0)
                slices_filled = int(data.get("slices_filled", 0) or 0)
                capped_events = int(data.get("volume_capped_events", 0) or 0)
                spread_bps = float(data.get("spread_bps", data.get("predictive_spread_bps", 0.0)) or 0.0)
                completion_rate = self._completion_rate(data, requested_qty, filled_qty, slices_attempted, slices_filled)
                slippage_bps = self._slippage_bps(data, execution_price, data.get("reference_price", data.get("mid_price_at_signal", data.get("target_price", 0.0))))

                global_stats["total_orders"] += 1
                global_stats["total_volume_usd"] += size
                global_stats["weighted_order_size_sum"] += size
                global_stats["weighted_pr_sum"] += realized_pr * size
                global_stats["weighted_spread_sum"] += spread_bps * size
                global_stats["requested_qty_sum"] += max(requested_qty, 0.0)
                global_stats["filled_qty_sum"] += max(filled_qty, 0.0)
                global_stats.setdefault("weighted_slippage_sum", 0.0)
                global_stats["weighted_slippage_sum"] += slippage_bps * size

                asset_entry = stats_by_asset[asset]
                asset_entry["total_orders"] += 1
                asset_entry["total_volume_usd"] += size
                asset_entry["weighted_order_size_sum"] += size
                asset_entry["weighted_pr_sum"] += realized_pr * size
                asset_entry["weighted_spread_sum"] += spread_bps * size
                asset_entry["requested_qty_sum"] += max(requested_qty, 0.0)
                asset_entry["filled_qty_sum"] += max(filled_qty, 0.0)
                asset_entry.setdefault("weighted_slippage_sum", 0.0)
                asset_entry["weighted_slippage_sum"] += slippage_bps * size

                if strat == "TWAP":
                    global_stats["twap_orders"] += 1
                    global_stats["total_capped_events"] += capped_events
                    global_stats["total_slices_attempted"] += slices_attempted
                    global_stats["total_slices_filled"] += slices_filled

                    asset_entry["twap_orders"] += 1
                    asset_entry["total_capped_events"] += capped_events
                    asset_entry["total_slices_attempted"] += slices_attempted
                    asset_entry["total_slices_filled"] += slices_filled

        return self._finalize_metrics(global_stats, stats_by_asset)

    def _finalize_metrics(self, global_stats: dict[str, Any], stats_by_asset: dict[str, Any]) -> dict[str, Any]:
        total_orders = global_stats["total_orders"]
        total_volume = global_stats["total_volume_usd"]
        twap_orders = global_stats["twap_orders"]
        total_capped_events = global_stats["total_capped_events"]
        total_attempted = global_stats["total_slices_attempted"]
        total_filled = global_stats["total_slices_filled"]

        global_summary = {
            "total_orders": total_orders,
            "total_volume_usd": total_volume,
            "twap_orders": twap_orders,
            "volume_capped_ratio": (total_capped_events / total_attempted) if total_attempted > 0 else 0.0,
            "completion_rate": (total_filled / total_attempted) if total_attempted > 0 else 0.0,
            "true_completion_rate": (
                global_stats["filled_qty_sum"] / global_stats["requested_qty_sum"]
                if global_stats["requested_qty_sum"] > 0
                else 0.0
            ),
            "realized_participation_rate_mean": (
                global_stats["weighted_pr_sum"] / global_stats["weighted_order_size_sum"]
                if global_stats["weighted_order_size_sum"] > 0
                else 0.0
            ),
            "avg_observed_spread_bps": (
                global_stats["weighted_spread_sum"] / global_stats["weighted_order_size_sum"]
                if global_stats["weighted_order_size_sum"] > 0
                else 0.0
            ),
            "avg_slippage_bps": (
                global_stats.get("weighted_slippage_sum", 0.0) / global_stats["weighted_order_size_sum"]
                if global_stats["weighted_order_size_sum"] > 0
                else 0.0
            ),
            "total_capped_events": total_capped_events,
        }

        assets_summary: dict[str, Any] = {}
        for asset, data in stats_by_asset.items():
            weighted_size = data["weighted_order_size_sum"]
            attempted = data["total_slices_attempted"]
            filled = data["total_slices_filled"]
            assets_summary[asset] = {
                "total_orders": data["total_orders"],
                "total_volume_usd": data["total_volume_usd"],
                "twap_orders": data["twap_orders"],
                "volume_capped_ratio": (data["total_capped_events"] / attempted) if attempted > 0 else 0.0,
                "completion_rate": (filled / attempted) if attempted > 0 else 0.0,
                "true_completion_rate": (
                    data["filled_qty_sum"] / data["requested_qty_sum"] if data["requested_qty_sum"] > 0 else 0.0
                ),
                "realized_participation_rate_mean": (
                    data["weighted_pr_sum"] / weighted_size if weighted_size > 0 else 0.0
                ),
                "avg_observed_spread_bps": (
                    data["weighted_spread_sum"] / weighted_size if weighted_size > 0 else 0.0
                ),
                "avg_slippage_bps": (
                    data.get("weighted_slippage_sum", 0.0) / weighted_size if weighted_size > 0 else 0.0
                ),
                "total_capped_events": data["total_capped_events"],
            }

        return {"global": global_summary, "assets": assets_summary}

    @staticmethod
    def _completion_rate(
        data: dict[str, Any],
        requested_qty: float,
        filled_qty: float,
        slices_attempted: int,
        slices_filled: int,
    ) -> float:
        if requested_qty > 0:
            return max(0.0, min(1.0, filled_qty / requested_qty))
        if slices_attempted > 0:
            return max(0.0, min(1.0, slices_filled / slices_attempted))
        return 0.0

    @staticmethod
    def _slippage_bps(data: dict[str, Any], execution_price: float, reference_price: Any) -> float:
        try:
            ref = float(reference_price or 0.0)
        except (TypeError, ValueError):
            ref = 0.0
        if execution_price <= 0 or ref <= 0:
            return 0.0
        return ((execution_price - ref) / ref) * 10_000.0
