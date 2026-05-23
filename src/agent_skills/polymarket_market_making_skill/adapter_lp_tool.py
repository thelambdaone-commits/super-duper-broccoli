import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("LpToolAdapter")


class LpToolAdapter:
    """Bridge between the polymarket_lp_tool (submodule in agents/) and the existing
    market-making skill and execution pipeline.

    Provides access to:
      - SimplePricePolicy (repricing logic based on CLOB liquidity rewards delta)
      - CustomPricingRulesStore (per-token + side pricing rules persisted as JSON)
      - RewardMonitor (fetch CLOB liquidity reward spread data)

    Usage:
        adapter = LpToolAdapter()
        decision = adapter.decide_price(
            token_id="12345",
            side="BUY",
            current_price=0.45,
            mid_price=0.50,
            delta=0.03,
            tick_size=0.01,
        )
    """

    def __init__(self, rules_path: Optional[Path] = None):
        self.rules_path = rules_path or Path("config/lp_custom_pricing_rules.json")
        self._rules: Dict[str, Any] = {}
        self._load_rules()

    # ── Public API ──

    def decide_price(
        self,
        token_id: str,
        side: str,
        current_price: float,
        mid_price: float,
        delta: float,
        tick_size: float = 0.01,
    ) -> Dict[str, Any]:
        """Apply the LP tool's SimplePricePolicy logic to decide whether to keep,
        cancel, or reprice an existing limit order.

        Returns dict with keys:
          - action: "keep" | "cancel" | "reprice"
          - new_price: float (if repricing)
          - reason: str
        """
        rule = self._get_rule(token_id, side)
        # coarse vs fine tick logic adapted from SimplePricePolicy
        is_fine_tick = tick_size < 0.01
        band = self._compute_band(delta, tick_size)

        distance = abs(current_price - mid_price)
        distance_ratio = distance / delta if delta > 0 else 1.0

        if is_fine_tick:
            return self._fine_tick_decision(current_price, mid_price, distance_ratio, delta, rule)
        else:
            return self._coarse_tick_decision(current_price, mid_price, distance, band, delta, rule)

    def get_custom_rule(self, token_id: str, side: str) -> Optional[Dict[str, Any]]:
        return self._rules.get(f"{token_id}:{side.upper()}")

    def set_custom_rule(self, token_id: str, side: str, rule: Dict[str, Any]) -> None:
        key = f"{token_id}:{side.upper()}"
        self._rules[key] = rule
        self._save_rules()

    # ── Internal ──

    def _load_rules(self) -> None:
        if self.rules_path and self.rules_path.exists():
            try:
                with open(self.rules_path) as f:
                    self._rules = json.load(f)
            except Exception as e:
                logger.warning("Failed to load custom pricing rules: %s", e)

    def _save_rules(self) -> None:
        if self.rules_path:
            self.rules_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.rules_path, "w") as f:
                json.dump(self._rules, f, indent=2)

    def _get_rule(self, token_id: str, side: str) -> Optional[Dict[str, Any]]:
        return self._rules.get(f"{token_id}:{side.upper()}")

    @staticmethod
    def _compute_band(delta: float, tick_size: float) -> float:
        if tick_size == 0:
            return 0.0
        return (delta // tick_size) * tick_size

    def _coarse_tick_decision(
        self,
        price: float,
        mid: float,
        distance: float,
        band: float,
        delta: float,
        rule: Optional[Dict],
    ) -> Dict[str, Any]:
        if rule:
            return self._apply_rule(price, mid, rule)
        levels = int(band / 0.01) if band > 0 else 1
        if levels <= 2:
            return {"action": "cancel", "new_price": None, "reason": f"Only {levels} levels, cancelling"}
        target_distance = band * 0.5 if band > 0 else delta * 0.5
        if distance < target_distance * 0.4:
            new_price = mid + target_distance if price > mid else mid - target_distance
            return {"action": "reprice", "new_price": round(new_price, 4), "reason": "Too close to mid"}
        return {"action": "keep", "new_price": price, "reason": "Within acceptable range"}

    def _fine_tick_decision(
        self,
        price: float,
        mid: float,
        distance_ratio: float,
        delta: float,
        rule: Optional[Dict],
    ) -> Dict[str, Any]:
        if rule:
            return self._apply_rule(price, mid, rule)
        if 0.4 <= distance_ratio <= 0.6:
            return {"action": "keep", "new_price": price, "reason": "Optimal distance (0.4-0.6 delta)"}
        if distance_ratio < 0.4:
            target = mid + (0.5 * delta) if price > mid else mid - (0.5 * delta)
            return {"action": "reprice", "new_price": round(target, 4), "reason": "Move outward to 0.5*delta"}
        target = mid + (0.5 * delta) if price > mid else mid - (0.5 * delta)
        return {"action": "reprice", "new_price": round(target, 4), "reason": "Move inward to 0.5*delta"}

    @staticmethod
    def _apply_rule(price: float, mid: float, rule: Dict) -> Dict[str, Any]:
        target = rule.get("target_price")
        if target is not None:
            return {"action": "reprice", "new_price": float(target), "reason": f"Custom rule: target={target}"}
        return {"action": "keep", "new_price": price, "reason": "Custom rule: keep"}
