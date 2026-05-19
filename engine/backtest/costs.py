from dataclasses import dataclass


@dataclass
class CostModel:
    spread_bps: float = 1.0
    commission_bps: float = 0.0
    slippage_bps: float = 0.5
    min_cost: float = 0.0

    def total_cost(self, trade_value: float) -> float:
        cost = trade_value * (self.spread_bps + self.commission_bps + self.slippage_bps) / 10000
        return max(cost, self.min_cost)
