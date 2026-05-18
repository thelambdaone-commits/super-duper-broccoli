from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import pandas as pd


@dataclass
class TrainingPipelinePredictiveAdapter:
    """
    Bridges a trained TrainingPipeline into the predictive-gate interface.

    This keeps the runtime simple: the bot can ask for a prediction using the
    latest registered features without duplicating inference logic.
    """

    pipeline: Any
    ticker: str

    def predict_winning_bet(
        self,
        df_market_ticks: pd.DataFrame,
        clob_price_yes: float,
        timestamp_resolution: float,
    ) -> dict[str, Any]:
        vector = self._resolve_feature_vector(df_market_ticks)
        if vector is None:
            return {
                "pari_approuve": False,
                "probability_win": 0.5,
                "absolute_edge": 0.0,
                "clob_price": clob_price_yes,
                "conclusion": "REJECT_NO_FEATURES",
                "timestamp_resolution": timestamp_resolution,
            }

        prediction = self.pipeline.predict(self.ticker, vector)
        if not prediction:
            return {
                "pari_approuve": False,
                "probability_win": 0.5,
                "absolute_edge": 0.0,
                "clob_price": clob_price_yes,
                "conclusion": "REJECT_NO_MODEL",
                "timestamp_resolution": timestamp_resolution,
            }

        probability_win = float(prediction.get("prob_up", 0.5))
        absolute_edge = probability_win - float(clob_price_yes)
        pari_approuve = absolute_edge >= 0.07
        return {
            "pari_approuve": pari_approuve,
            "probability_win": probability_win,
            "absolute_edge": absolute_edge,
            "clob_price": clob_price_yes,
            "timestamp_resolution": timestamp_resolution,
            "conclusion": "EXECUTE_TRADE" if pari_approuve else "REJECT_NO_EDGE",
            "dissimilarity_index": float(prediction.get("dissimilarity_index", 0.0)),
            "ood_alert": bool(prediction.get("ood_alert", False)),
        }

    def _resolve_feature_vector(self, df_market_ticks: pd.DataFrame) -> Optional[Any]:
        if df_market_ticks is None or df_market_ticks.empty:
            return self.pipeline.latest_features_as_vector(self.ticker)

        row = df_market_ticks.iloc[-1]
        if hasattr(row, "to_frame"):
            return row.to_frame().T.values
        return df_market_ticks.values[-1:]
