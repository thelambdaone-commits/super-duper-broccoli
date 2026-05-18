from __future__ import annotations

import asyncio
import math
import logging
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger("FragmentedOrderExecutor")


@dataclass(frozen=True)
class FragmentedOrderConfig:
    twap_default_slices: int = 5
    twap_interval_seconds: float = 15.0
    max_first_level_participation_rate: float = 0.10
    max_participation_rate: float = 0.10
    min_size_for_fragmentation_usd: float = 0.0


class FragmentedOrderExecutor:
    """
    Executes passive-only signals using time-sliced limit orders when fragmentation
    improves expected slippage, otherwise falls back to the immediate executor.
    """

    def __init__(
        self,
        config: dict[str, Any] | FragmentedOrderConfig | None = None,
        exchange_client: Any = None,
        immediate_executor: Any = None,
        feature_store: Any = None,
    ) -> None:
        if config is None:
            config = FragmentedOrderConfig()
        elif isinstance(config, dict):
            config = FragmentedOrderConfig(
                twap_default_slices=int(config.get("twap_default_slices", 5)),
                twap_interval_seconds=float(config.get("twap_interval_seconds", 15.0)),
                max_first_level_participation_rate=float(
                    config.get("max_first_level_participation_rate", 0.10)
                ),
                max_participation_rate=float(config.get("max_participation_rate", 0.10)),
                min_size_for_fragmentation_usd=float(
                    config.get("min_size_for_fragmentation_usd", 0.0)
                ),
            )

        self.config = config
        self.exchange_client = exchange_client
        self.immediate_executor = immediate_executor or exchange_client
        self.feature_store = feature_store

    async def execute(self, signal: dict, context: Any) -> dict[str, Any]:
        passive_only = bool(signal.get("execution_preference") == "PASSIVE_ONLY" or signal.get("passive_only"))
        if not passive_only:
            return await self._execute_immediate(signal, context)

        if not self._should_fragment(signal, context):
            logger.info("PASSIVE_ONLY detected but fragmentation not required; using immediate execution.")
            return await self._execute_immediate(signal, context)

        return await self._execute_twap(signal, context)

    async def _execute_immediate(self, signal: dict, context: Any) -> dict[str, Any]:
        executor = self._resolve_executor(context)
        if executor is None:
            raise ValueError("Configuration Error: immediate executor is required but missing")

        payload = self._build_order_payload(signal)
        if hasattr(executor, "execute"):
            return await executor.execute(
                payload["ticker"],
                payload["side"],
                payload["price"],
                payload["size_usd"],
            )
        if hasattr(executor, "create_order"):
            return await executor.create_order(
                ticker=payload["ticker"],
                side=payload["side"],
                price=payload["price"],
                size=payload["size_usd"],
            )
        if callable(executor):
            return await executor(signal, context)
        raise ValueError("Configuration Error: immediate executor interface unsupported")

    async def _execute_twap(self, signal: dict, context: Any) -> dict[str, Any]:
        executor = self._resolve_executor(context)
        if executor is None:
            raise ValueError("Configuration Error: fragmented executor requires an underlying executor")

        payload = self._build_order_payload(signal)
        total_size_usd = max(0.0, float(payload["size_usd"]))
        min_notional = self._get_min_notional()
        if total_size_usd < min_notional:
            logger.warning(
                "TWAP parent order for %s is below Polymarket minimum notional (%.2f < %.2f); "
                "falling back to immediate execution.",
                payload["ticker"],
                total_size_usd,
                min_notional,
            )
            return await self._execute_immediate(signal, context)

        target_slices = max(1, int(self.config.twap_default_slices))
        max_possible_slices = max(1, int(math.floor(total_size_usd / min_notional)))
        slices = min(target_slices, max_possible_slices)
        if slices < target_slices:
            logger.info(
                "Adjusting TWAP slices for %s: %s -> %s to keep each child order above %.2f USD",
                payload["ticker"],
                target_slices,
                slices,
                min_notional,
            )

        executed_slices = 0
        filled_amount_usd = 0.0
        slice_results: list[dict[str, Any]] = []
        observed_market_volumes: list[float] = []
        capped_events = 0
        remaining_usd = total_size_usd
        for index in range(slices):
            market_volume = self._get_recent_market_volume(payload["ticker"], signal)
            observed_market_volumes.append(market_volume)
            slice_target_usd = remaining_usd / max(1, slices - index)
            max_allowed_usd = market_volume * self.config.max_participation_rate if market_volume > 0 else slice_target_usd
            slice_size_usd = min(slice_target_usd, max_allowed_usd if max_allowed_usd > 0 else slice_target_usd, remaining_usd)
            if market_volume > 0 and slice_target_usd > max_allowed_usd > 0 and slice_size_usd < slice_target_usd:
                capped_events += 1
            if slice_size_usd <= 0:
                logger.info(
                    "Skipping TWAP slice %s/%s for %s because the dynamic participation cap is zero.",
                    index + 1,
                    slices,
                    payload["ticker"],
                )
                slice_results.append(
                    {
                        "status": "SKIPPED",
                        "reason": "ZERO_PARTICIPATION_CAP",
                        "slice_index": index + 1,
                        "market_volume": market_volume,
                    }
                )
                if index < slices - 1:
                    await asyncio.sleep(self.config.twap_interval_seconds)
                continue

            logger.info(
                "TWAP slice %s/%s for %s: %.4f USD (market volume %.2f, cap %.2f%%)",
                index + 1,
                slices,
                payload["ticker"],
                slice_size_usd,
                market_volume,
                self.config.max_participation_rate * 100.0,
            )
            result = await self._place_slice(executor, payload, slice_size_usd, context)
            slice_results.append(result)
            if self._is_slice_filled(result):
                executed_slices += 1
                filled_amount_usd += slice_size_usd
                remaining_usd = max(0.0, remaining_usd - slice_size_usd)

            if index < slices - 1:
                await asyncio.sleep(self.config.twap_interval_seconds)

        avg_market_volume = (
            sum(observed_market_volumes) / len(observed_market_volumes)
            if observed_market_volumes
            else 0.0
        )
        realized_pr = (
            filled_amount_usd / sum(observed_market_volumes)
            if observed_market_volumes and sum(observed_market_volumes) > 0
            else 0.0
        )

        report = {
            "status": "SUCCESS" if executed_slices > 0 else "FAILED",
            "strategy": "TWAP",
            "ticker": payload["ticker"],
            "side": payload["side"],
            "target_price": payload["price"],
            "total_requested_usd": total_size_usd,
            "slices_attempted": slices,
            "slices_filled": executed_slices,
            "total_filled_usd": filled_amount_usd,
            "planned_vs_actual_slices": f"{slices}/{len(slice_results)}",
            "avg_market_volume_observed": avg_market_volume,
            "realized_participation_rate": realized_pr,
            "volume_capped_events": capped_events,
            "execution_path": "fragmented_twap",
            "slice_results": slice_results,
        }
        return report

    async def _place_slice(self, executor: Any, payload: dict[str, Any], slice_size_usd: float, context: Any) -> dict[str, Any]:
        contracts_qty = self._notional_to_contracts(slice_size_usd, payload["price"])
        if hasattr(executor, "execute"):
            result = await executor.execute(payload["ticker"], payload["side"], payload["price"], contracts_qty)
            if isinstance(result, dict):
                result = dict(result)
                result.setdefault("slice_size_usd", slice_size_usd)
                result.setdefault("slice_size_contracts", contracts_qty)
            return result if isinstance(result, dict) else {"status": "UNKNOWN", "raw": result}
        if hasattr(executor, "create_order"):
            result = await executor.create_order(
                ticker=payload["ticker"],
                side=payload["side"],
                price=payload["price"],
                size=contracts_qty,
            )
            return result if isinstance(result, dict) else {"status": "UNKNOWN", "raw": result}
        if callable(executor):
            result = await executor(payload, context)
            return result if isinstance(result, dict) else {"status": "UNKNOWN", "raw": result}
        raise ValueError("Configuration Error: executor interface unsupported for TWAP slice")

    @staticmethod
    def _notional_to_contracts(size_usd: float, price: float) -> float:
        if price <= 0:
            return 0.0
        return max(0.0, float(size_usd) / float(price))

    def _get_min_notional(self) -> float:
        return 5.0

    def _resolve_executor(self, context: Any) -> Any:
        return self.immediate_executor or getattr(context, "executor", None)

    def _should_fragment(self, signal: dict, context: Any) -> bool:
        if signal.get("execution_preference") == "PASSIVE_ONLY" or signal.get("passive_only"):
            return True

        size_usd = float(signal.get("size_usd", 0.0) or 0.0)
        if size_usd < self.config.min_size_for_fragmentation_usd:
            return False

        liquidity = (
            signal.get("microstructure_liquidity")
            or signal.get("market_features")
            or {}
        )
        if not isinstance(liquidity, dict):
            return False

        bid_depth = float(liquidity.get("bid_depth_3", liquidity.get("bid_depth", 0.0)) or 0.0)
        ask_depth = float(liquidity.get("ask_depth_3", liquidity.get("ask_depth", 0.0)) or 0.0)
        best_depth = max(bid_depth, ask_depth)
        if best_depth <= 0:
            return False
        return size_usd > best_depth * self.config.max_first_level_participation_rate

    def _get_recent_market_volume(self, ticker: str, signal: dict) -> float:
        for candidate in (
            signal.get("market_volume"),
            signal.get("recent_volume"),
            signal.get("volume"),
        ):
            try:
                if candidate is not None:
                    return max(0.0, float(candidate))
            except (TypeError, ValueError):
                pass

        store = self.feature_store or signal.get("feature_store") or signal.get("store")
        if not store or not ticker:
            return 0.0

        try:
            history = store.get_feature_history(ticker, "volume", since_ts=0.0, limit=20)
        except Exception:
            return 0.0
        if not history:
            return 0.0

        values = []
        for row in history[-5:]:
            try:
                values.append(float(row.get("value", 0.0)))
            except (TypeError, ValueError):
                continue
        return max(0.0, sum(values) / len(values)) if values else 0.0

    def _build_order_payload(self, signal: dict) -> dict[str, Any]:
        ticker = str(signal.get("asset") or signal.get("ticker") or signal.get("token_id") or "").strip()
        side = str(signal.get("direction") or signal.get("side") or signal.get("action") or "BUY").upper()
        price = float(signal.get("price") or signal.get("target_price") or signal.get("execution_price") or 0.0)
        size_usd = float(signal.get("size_usd") or signal.get("size") or signal.get("allocated_capital") or 0.0)
        return {
            "ticker": ticker,
            "side": side,
            "price": price,
            "size_usd": size_usd,
        }

    def _is_slice_filled(self, result: Any) -> bool:
        if not isinstance(result, dict):
            return bool(result)
        status = str(result.get("status", "")).upper()
        return status not in {"FAILED", "REJECTED", "ERROR", "TAKER_FAILED", "CANCEL_FAILED"}
