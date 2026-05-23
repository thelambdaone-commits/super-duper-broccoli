import logging
from typing import Any

import numpy as np
from sklearn.calibration import calibration_curve

logger = logging.getLogger("CalibrationMetrics")


def calculate_dissimilarity_index(
    X_train: np.ndarray,
    X_live: np.ndarray,
) -> float:
    train = np.asarray(X_train, dtype=np.float64)
    live = np.asarray(X_live, dtype=np.float64)
    if train.ndim != 2 or live.ndim != 2 or train.size == 0 or live.size == 0:
        return 0.0
    mean = np.mean(train, axis=0)
    std = np.std(train, axis=0)
    std = np.where(std < 1e-8, 1.0, std)
    z = np.abs((live[-1] - mean) / std)
    return float(np.max(z))


def audit_model_calibration(
    y_true: np.ndarray,
    y_prob_predicted: np.ndarray,
    n_bins: int = 10,
) -> dict[str, Any]:
    y_true_arr = np.asarray(y_true, dtype=np.int32)
    y_prob_arr = np.asarray(y_prob_predicted, dtype=np.float64)
    if y_prob_arr.ndim == 2:
        y_prob_arr = y_prob_arr[:, 1]
    true_freq, pred_prob = calibration_curve(y_true_arr, y_prob_arr, n_bins=n_bins, strategy="uniform")
    ece = float(np.mean(np.abs(true_freq - pred_prob))) if len(true_freq) else 0.0
    return {
        "ece": round(ece, 6),
        "true_frequencies": true_freq.tolist(),
        "pred_probabilities": pred_prob.tolist(),
        "n_bins": int(n_bins),
    }
