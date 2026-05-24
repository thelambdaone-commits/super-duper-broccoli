import logging
import os
from typing import Any, Optional

import numpy as np

from core.training.model_manager import prepare_prediction_input
from utils.feature_store import FeatureStore


logger = logging.getLogger("TrainingPipeline.Prediction")


def predict(
    ticker: str,
    features: np.ndarray,
    model_dir: str,
    models: dict[str, Any],
    calibrated_models: dict[str, Any],
    calibrators: dict[str, Any],
    store: Optional[FeatureStore] = None,
) -> Optional[dict]:
    model = models.get(ticker)
    if model is None:
        model_path = os.path.join(model_dir, f"{ticker}_hybrid.pkl")
        if os.path.exists(model_path):
            from user_data.freqaimodels.HybridQuantModel import HybridQuantModel
            model = HybridQuantModel().load(model_path)
            models[ticker] = model
        else:
            logger.warning(f"No model found for {ticker}")
            return None

    calibrated = calibrated_models.get(ticker)
    if calibrated is None:
        calibrated_path = os.path.join(model_dir, f"{ticker}_calibrated.pkl")
        if os.path.exists(calibrated_path):
            try:
                import joblib
                calibrated = joblib.load(calibrated_path)
                calibrated_models[ticker] = calibrated
            except Exception as e:
                logger.warning(f"Failed to load calibrated model for {ticker}: {e}")

    prediction_input = prepare_prediction_input(model, features)
    proba = (
        calibrated.predict_proba(prediction_input)
        if calibrated is not None
        else model.predict_proba(prediction_input)
    )
    di = 0.0
    ood_alert = False
    if hasattr(model, "_training_mean") and hasattr(model, "_training_std"):
        live = np.asarray(features, dtype=np.float64)
        mean = np.asarray(model._training_mean, dtype=np.float64)
        std = np.asarray(model._training_std, dtype=np.float64)
        std = np.where(std < 1e-8, 1.0, std)
        if live.ndim == 2 and live.shape[1] == mean.shape[0]:
            di = float(np.max(np.abs((live[-1] - mean) / std)))
            threshold = float(getattr(model, "_ood_di_threshold", os.getenv("OOD_DI_THRESHOLD", "3.0")))
            ood_alert = di > threshold
            if ood_alert:
                logger.warning(f"OOD dissimilarity spike for {ticker}: DI={di:.2f} threshold={threshold:.2f}")

    calibrator = calibrators.get(ticker)
    if calibrator is None:
        calibrator_path = os.path.join(model_dir, f"{ticker}_calibrator.pkl")
        if os.path.exists(calibrator_path):
            try:
                from strategies.probability_calibrator import ProbabilityCalibrator
                calibrator = ProbabilityCalibrator().load(calibrator_path)
                calibrators[ticker] = calibrator
            except Exception as e:
                logger.warning(f"Failed to load calibrator for {ticker}: {e}")
    if calibrator is not None:
        try:
            proba = calibrator.predict_proba(proba)
        except Exception as e:
            logger.warning(f"Calibrated prediction failed for {ticker}: {e}")

    direction = 1 if proba[0, 1] >= 0.5 else -1
    return {
        "ticker": ticker,
        "prob_up": float(proba[0, 1]),
        "prob_down": float(proba[0, 0]),
        "direction": int(direction),
        "signal": "BUY" if direction == 1 else "SELL",
        "dissimilarity_index": di,
        "ood_alert": ood_alert,
    }


def latest_features_as_vector(
    ticker: str,
    feature_registry: dict[str, Any],
    store: FeatureStore,
    max_history: int = 50,
) -> Optional[np.ndarray]:
    registered = feature_registry.get(ticker)
    if not registered:
        return None
    feature_names, target_feature = registered if isinstance(registered, tuple) else (registered, "")
    series_list: list[np.ndarray] = []
    for fname in feature_names:
        if fname == target_feature:
            continue
        history = store.get_feature_history(ticker, fname, limit=max_history)
        if len(history) < 2:
            return None
        vals = np.array([h["value"] for h in history], dtype=np.float32)
        series_list.append(vals)
    min_len = min(len(s) for s in series_list)
    X = np.column_stack([s[-min_len:] for s in series_list])
    return X[-1:]
