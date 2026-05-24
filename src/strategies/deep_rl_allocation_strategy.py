import logging
import numpy as np
from typing import Any, Mapping, Optional
from .base_strategy import MarketFeatures, StrategyParameters, StrategySignal, coerce_features, PolymarketStrategy

logger = logging.getLogger("DeepRLAllocationStrategy")

class DeepRLAllocationStrategy(PolymarketStrategy):
    """
    Asset allocation strategy inspired by HKUDS/AI-Trader.
    Uses Reinforcement Learning principles for portfolio optimization.
    
    Repository: https://github.com/HKUDS/AI-Trader
    """
    
    def __init__(self):
        super().__init__(
            strategy_id="deep_rl_allocation",
            name="Deep RL Portfolio Allocation",
            parameters=StrategyParameters(
                min_confidence=0.65,
                min_edge=0.015,
                max_spread=0.04
            )
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> Optional[StrategySignal]:
        """
        Generates signals using RL-based reward optimization.
        """
        features = coerce_features(features)
        # 1. State representation (Price + Volumes + NLP Sentiment)
        state = self._extract_state(features)
        
        # 2. RL Agent Inference (Action: Hold/Buy/Sell)
        # Placeholder for actual DDPG or PPO agent inference
        action_prob = self._get_agent_action(state, features)
        
        # 3. Calculate Edge based on action probability vs market price
        # If agent is 80% confident of UP and price is 0.50, edge is 0.30
        market_price = features.price
        edge = action_prob - market_price
        
        if edge > self.parameters.min_edge:
            return self._signal(
                features=features,
                side="BUY",
                confidence=action_prob,
                edge=edge,
                reason=f"RL Agent optimal allocation (p={action_prob:.2f})"
            )
        elif edge < -self.parameters.min_edge:
            return self._signal(
                features=features,
                side="SELL",
                confidence=abs(action_prob - 1.0),
                edge=abs(edge),
                reason=f"RL Agent optimal reduction (p={action_prob:.2f})"
            )
            
        return None

    def _extract_state(self, features: MarketFeatures) -> np.ndarray:
        # Combining quantitative features into a vector
        return np.array([
            features.price,
            features.spread,
            features.order_imbalance,
            float((features.metadata or {}).get("known_wallet_flow_score", 0.0) or 0.0),
        ])

    def _get_agent_action(self, state: np.ndarray, features: MarketFeatures) -> float:
        # Deterministic proxy until a real RL policy is wired in.
        base_p = float(features.ml_probability if features.ml_probability is not None else 0.5)
        order_bias = float(np.clip(state[2] * 0.05, -0.1, 0.1))
        flow_bias = float(np.clip(state[3] * 0.03, -0.1, 0.1))
        return float(np.clip(base_p + order_bias + flow_bias, 0.0, 1.0))
