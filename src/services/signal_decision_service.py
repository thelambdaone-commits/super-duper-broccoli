from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("SignalDecisionService")


class SignalDecisionService:
    def __init__(
        self,
        predictive_gate: Any,
        risk_engine: Any,
        ledger: Any,
        snapshot_mgr: Any,
    ) -> None:
        self.predictive_gate = predictive_gate
        self.risk_engine = risk_engine
        self.ledger = ledger
        self.snapshot_mgr = snapshot_mgr

    async def apply_predictive_gate(self, signal: dict) -> tuple[dict, bool]:
        if self.predictive_gate is None:
            return signal, True
        allowed, reason = self.predictive_gate.validate_signal(signal)
        if not allowed:
            logger.info("💤 [PREDICTIVE GATE] Signal rejected: %s", reason)
            return signal, False
        logger.info(
            "🔮 [PREDICTIVE GATE] Signal validated: P(win)=%s, Edge=%s",
            f"{signal.get('predictive_probability', 0.0):.1%}",
            f"{signal.get('predictive_edge', 0.0):+.1%}",
        )
        return signal, True

    def attach_microstructure_context(self, signal: dict) -> dict:
        snapshot = None
        try:
            snapshot = self.snapshot_mgr.get_latest(category="SYSTEM", component="CLOB_ORDERBOOK")
        except Exception as exc:
            logger.debug("Unable to fetch latest CLOB snapshot: %s", exc)

        microstructure = self.build_microstructure_context(signal, snapshot)
        if not microstructure:
            return signal

        enriched = dict(signal)
        enriched["microstructure_context"] = microstructure
        return enriched

    async def apply_portfolio_risk_gate(self, signal: dict) -> tuple[bool, str]:
        if self.risk_engine is None:
            return True, "Risk engine unavailable"

        try:
            capital_summary = self.ledger.get_capital_summary() if self.ledger else {}
            current_portfolio_value = float(
                capital_summary.get("total_capital")
                or capital_summary.get("available_capital")
                or 0.0
            )
        except Exception as exc:
            logger.warning("Failed to fetch portfolio capital for risk gate: %s", exc)
            current_portfolio_value = 0.0

        active_positions: dict[str, float] = {}
        if self.ledger is not None:
            try:
                for pos in self.ledger.get_open_positions():
                    ticker = str(pos.get("ticker", "")).upper()
                    active_positions[ticker] = active_positions.get(ticker, 0.0) + float(
                        pos.get("capital_engaged")
                        or pos.get("size", 0.0) * pos.get("entry_price", 0.0)
                    )
            except Exception as exc:
                logger.warning("Failed to fetch active positions for risk gate: %s", exc)

        try:
            allowed, reason = await self.risk_engine.validate_signal_risk(
                signal=signal,
                current_portfolio_value=current_portfolio_value,
                active_positions=active_positions,
            )
            return bool(allowed), str(reason)
        except Exception as exc:
            logger.warning("Portfolio risk gate failed open: %s", exc)
            return True, f"Risk gate unavailable: {exc}"

    def build_microstructure_context(self, signal: dict, snapshot: Any) -> dict[str, Any]:
        context: dict[str, Any] = {}
        if isinstance(snapshot, dict):
            context.update(
                {
                    "source": snapshot.get("source", "snapshot_manager"),
                    "token_id": snapshot.get("token_id") or snapshot.get("asset_id") or snapshot.get("ticker") or "",
                    "spread_bps": self._coerce_first_numeric(snapshot.get("spread_bps", 0.0)),
                    "order_imbalance": self._coerce_first_numeric(snapshot.get("order_imbalance", 0.0)),
                    "bid_depth_3": self._coerce_first_numeric(snapshot.get("bid_depth_3", snapshot.get("bid_depth", 0.0))),
                    "ask_depth_3": self._coerce_first_numeric(snapshot.get("ask_depth_3", snapshot.get("ask_depth", 0.0))),
                    "mid_price": self._coerce_first_numeric(snapshot.get("mid_price", snapshot.get("mid", signal.get("price", 0.0)))),
                    "timestamp": snapshot.get("timestamp"),
                }
            )

        if not context and isinstance(signal.get("microstructure_liquidity"), dict):
            liquidity = signal["microstructure_liquidity"]
            context.update(
                {
                    "source": "signal_payload",
                    "spread_bps": self._coerce_first_numeric(liquidity.get("spread_bps", 0.0)),
                    "order_imbalance": self._coerce_first_numeric(liquidity.get("order_imbalance", 0.0)),
                    "bid_depth_3": self._coerce_first_numeric(liquidity.get("bid_depth_3", liquidity.get("bid_depth", 0.0))),
                    "ask_depth_3": self._coerce_first_numeric(liquidity.get("ask_depth_3", liquidity.get("ask_depth", 0.0))),
                    "mid_price": self._coerce_first_numeric(liquidity.get("mid_price", signal.get("price", 0.0))),
                }
            )

        if not context and isinstance(signal.get("market_features"), dict):
            features = signal["market_features"]
            context.update(
                {
                    "source": "market_features",
                    "spread_bps": self._coerce_first_numeric(features.get("spread_bps", 0.0)),
                    "order_imbalance": self._coerce_first_numeric(features.get("order_imbalance", 0.0)),
                    "bid_depth_3": self._coerce_first_numeric(features.get("bid_depth_3", features.get("bid_depth", 0.0))),
                    "ask_depth_3": self._coerce_first_numeric(features.get("ask_depth_3", features.get("ask_depth", 0.0))),
                    "mid_price": self._coerce_first_numeric(features.get("mid_price", signal.get("price", 0.0))),
                }
            )

        if context:
            ticker = str(signal.get("ticker") or signal.get("asset") or signal.get("token_id") or "").upper()
            context["ticker"] = ticker
            context["liquidity_regime"] = self._classify_microstructure_regime(context)
        return context

    @staticmethod
    def _coerce_first_numeric(value: Any) -> float:
        if isinstance(value, (list, tuple)):
            for item in value:
                try:
                    return float(item)
                except (TypeError, ValueError):
                    continue
            return 0.0
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _classify_microstructure_regime(microstructure: dict[str, Any]) -> str:
        spread_bps = float(microstructure.get("spread_bps", 0.0) or 0.0)
        obi = float(microstructure.get("order_imbalance", 0.0) or 0.0)
        bid_depth = float(microstructure.get("bid_depth_3", 0.0) or 0.0)
        ask_depth = float(microstructure.get("ask_depth_3", 0.0) or 0.0)
        depth_total = bid_depth + ask_depth
        if spread_bps >= 500.0 or depth_total <= 0:
            return "THIN"
        if spread_bps <= 150.0 and abs(obi) >= 0.25:
            return "IMBALANCED"
        if spread_bps <= 200.0 and depth_total >= 200.0:
            return "LIQUID"
        return "NORMAL"
