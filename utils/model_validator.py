import logging
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Any
from scipy import stats

logger = logging.getLogger("ModelValidator")

class ModelValidator:
    def __init__(self, feature_store=None, snapshot_manager=None):
        self.store = feature_store
        self.sm = snapshot_manager

    def validate_performance(self, returns: pd.Series) -> dict[str, float]:
        """Calculates standard quant performance metrics."""
        if returns.empty: return {}

        sharpe = (returns.mean() / returns.std() * np.sqrt(252)) if returns.std() > 0 else 0
        downside_std = returns[returns < 0].std()
        sortino = (returns.mean() / downside_std * np.sqrt(252)) if downside_std > 0 else 0

        cum_returns = (1 + returns).cumprod()
        running_max = cum_returns.cummax()
        drawdown = (cum_returns - running_max) / running_max
        max_dd = drawdown.min()

        return {
            "sharpe_ratio": float(sharpe),
            "sortino_ratio": float(sortino),
            "max_drawdown": float(max_dd),
            "win_rate": float((returns > 0).mean()),
        }

    def detect_drift(self, reference_data: np.ndarray, current_data: np.ndarray, threshold: float = 0.05) -> dict[str, Any]:
        """Detects feature drift using Kolmogorov-Smirnov test."""
        if reference_data.size == 0 or current_data.size == 0:
            return {"drift_detected": False, "reason": "insufficient_data"}

        # KS test for distribution shift
        ks_stat, p_value = stats.ks_2samp(reference_data.flatten(), current_data.flatten())

        return {
            "drift_detected": p_value < threshold,
            "ks_stat": float(ks_stat),
            "p_value": float(p_value),
            "threshold": threshold
        }

    def check_calibration(self, y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 10) -> dict[str, Any]:
        """Calculates Expected Calibration Error (ECE)."""
        if y_true.size == 0: return {"ece": 0.0}

        bins = np.linspace(0., 1. + 1e-8, n_bins + 1)
        binids = np.digitize(y_prob, bins) - 1

        bin_sums = np.bincount(binids, weights=y_prob, minlength=len(bins)-1)
        bin_true = np.bincount(binids, weights=y_true, minlength=len(bins)-1)
        bin_total = np.bincount(binids, minlength=len(bins)-1)

        nonzero = bin_total > 0
        prob_pred = bin_sums[nonzero] / bin_total[nonzero]
        prob_true = bin_true[nonzero] / bin_total[nonzero]

        ece = np.sum(np.abs(prob_pred - prob_true) * (bin_total[nonzero] / len(y_true)))

        return {
            "ece": float(ece),
            "n_bins": n_bins,
            "reliable": ece < 0.1 # Heuristic
        }

    def run_health_check(self, ticker: str, model_id: str) -> dict[str, Any]:
        """Comprehensive health check for a specific ticker/model."""
        if not self.store:
            return {"error": "FeatureStore not connected"}

        try:
            # Fetch last 100 features for drift check
            current = self.store.get_feature_history(ticker, "mid_price", limit=100)
            reference = self.store.get_feature_history(ticker, "mid_price", limit=1000) # Simplified reference

            curr_vals = np.array([f["value"] for f in current])
            ref_vals = np.array([f["value"] for f in reference])

            drift = self.detect_drift(ref_vals, curr_vals)

            report = {
                "ticker": ticker,
                "model_id": model_id,
                "timestamp": datetime.utcnow().isoformat(),
                "drift_report": drift,
                "health": "CRITICAL" if drift["drift_detected"] else "HEALTHY",
            }

            if self.sm:
                self.sm.capture("HEALTH", f"model_{ticker}", report)

            return report
        except Exception as e:
            logger.error(f"Health check failed for {ticker}: {e}")
            return {"error": str(e)}
