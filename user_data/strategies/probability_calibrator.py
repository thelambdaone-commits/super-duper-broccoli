import logging
import os
import pickle
from typing import Any, Optional

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss

from config.constants import FUSION_MODES

logger = logging.getLogger("ProbabilityCalibrator")


class ProbabilityCalibrator:
    ALLOWED_DIR = os.getenv("MODEL_DIR", "user_data/models")

    def __init__(
        self,
        fusion_mode: str = "ensemble",
        platt_l1_ratio: float = 0.0,
        isotonic_out_of_bounds: str = "clip",
    ) -> None:
        if fusion_mode not in FUSION_MODES:
            raise ValueError(f"fusion_mode must be one of {FUSION_MODES}, got '{fusion_mode}'")
        self.fusion_mode = fusion_mode
        self.platt_l1_ratio = platt_l1_ratio
        self.isotonic_out_of_bounds = isotonic_out_of_bounds
        self._platt: Optional[LogisticRegression] = None
        self._isotonic: Optional[IsotonicRegression] = None
        self._fitted: bool = False
        self.calibration_log: dict[str, float] = {}

    @property
    def is_fitted(self) -> bool:
        return self._fitted

    def calibrate(
        self,
        oof_pred_proba: np.ndarray,
        y_true: np.ndarray,
        store: Optional[Any] = None,
        ticker: str = "",
        model_version: str = "",
    ) -> "ProbabilityCalibrator":
        if len(oof_pred_proba) < 10:
            raise ValueError(
                f"Need at least 10 out-of-fold samples, got {len(oof_pred_proba)}"
            )
        if len(np.unique(y_true)) < 2:
            raise ValueError("y_true must contain both classes (0 and 1)")

        proba_class1 = oof_pred_proba[:, 1] if oof_pred_proba.ndim == 2 else oof_pred_proba

        log_odds = np.clip(np.log(proba_class1 + 1e-12) - np.log(1.0 - proba_class1 + 1e-12), -20, 20)
        X_log_odds = log_odds.reshape(-1, 1)

        self._platt = LogisticRegression(l1_ratio=self.platt_l1_ratio, solver="lbfgs")
        self._platt.fit(X_log_odds, y_true)

        self._isotonic = IsotonicRegression(
            out_of_bounds=self.isotonic_out_of_bounds, increasing=True
        )
        self._isotonic.fit(proba_class1, y_true)

        if self.fusion_mode == "platt_only":
            calibrated = self._platt.predict_proba(X_log_odds)[:, 1]
        elif self.fusion_mode == "isotonic_only":
            calibrated = self._isotonic.predict(proba_class1)
        else:
            platt_cal = self._platt.predict_proba(X_log_odds)[:, 1]
            iso_cal = self._isotonic.predict(proba_class1)
            calibrated = 0.5 * platt_cal + 0.5 * iso_cal

        calibrated = np.clip(calibrated, 0.0, 1.0)

        raw_brier = float(brier_score_loss(y_true, proba_class1))
        cal_brier = float(brier_score_loss(y_true, calibrated))
        improvement = raw_brier - cal_brier

        self.calibration_log = {
            "raw_brier": round(raw_brier, 6),
            "calibrated_brier": round(cal_brier, 6),
            "brier_improvement": round(improvement, 6),
            "n_samples": len(oof_pred_proba),
            "fusion_mode": self.fusion_mode,
        }
        logger.info(
            f"Calibration complete: raw_brier={raw_brier:.6f} "
            f"calibrated_brier={cal_brier:.6f} "
            f"improvement={improvement:+.6f} (fusion={self.fusion_mode})"
        )

        if store is not None:
            try:
                store.record_calibration(
                    ticker=ticker,
                    model_version=model_version,
                    raw_brier=round(raw_brier, 6),
                    calibrated_brier=round(cal_brier, 6),
                    brier_improvement=round(improvement, 6),
                    n_samples=len(oof_pred_proba),
                    fusion_mode=self.fusion_mode,
                )
            except Exception as e:
                logger.warning(f"Failed to persist calibration metrics: {e}")

        self._fitted = True
        return self

    def predict_proba(self, raw_proba: np.ndarray) -> np.ndarray:
        if not self._fitted:
            raise RuntimeError("Calibrator not fitted. Call calibrate() first.")

        proba_class1 = raw_proba[:, 1] if raw_proba.ndim == 2 else raw_proba
        proba_class1 = np.asarray(proba_class1, dtype=np.float64)

        log_odds = np.clip(
            np.log(proba_class1 + 1e-12) - np.log(1.0 - proba_class1 + 1e-12),
            -20, 20,
        )

        if self.fusion_mode == "platt_only":
            calibrated = self._platt.predict_proba(log_odds.reshape(-1, 1))[:, 1]
        elif self.fusion_mode == "isotonic_only":
            calibrated = self._isotonic.predict(proba_class1)
        else:
            platt_cal = self._platt.predict_proba(log_odds.reshape(-1, 1))[:, 1]
            iso_cal = self._isotonic.predict(proba_class1)
            calibrated = 0.5 * platt_cal + 0.5 * iso_cal

        calibrated = np.clip(calibrated, 0.0, 1.0)

        result = np.zeros((len(calibrated), 2), dtype=np.float64)
        result[:, 1] = calibrated
        result[:, 0] = 1.0 - calibrated
        return result

    def save(self, path: str) -> str:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            pickle.dump(
                {
                    "fusion_mode": self.fusion_mode,
                    "platt_l1_ratio": self.platt_l1_ratio,
                    "isotonic_out_of_bounds": self.isotonic_out_of_bounds,
                    "platt": self._platt,
                    "isotonic": self._isotonic,
                    "fitted": self._fitted,
                    "calibration_log": self.calibration_log,
                },
                fh,
            )
        logger.info("ProbabilityCalibrator saved to %s", path)
        return path

    def load(self, path: str) -> "ProbabilityCalibrator":
        resolved = os.path.abspath(path)
        allowed = os.path.abspath(self.ALLOWED_DIR)
        if not resolved.startswith(allowed):
            raise ValueError(f"Refusing to load from outside {allowed}: {path}")
        with open(path, "rb") as fh:
            data = pickle.load(fh)
        self.fusion_mode = data.get("fusion_mode", self.fusion_mode)
        self.platt_l1_ratio = data.get("platt_l1_ratio", self.platt_l1_ratio)
        self.isotonic_out_of_bounds = data.get(
            "isotonic_out_of_bounds", self.isotonic_out_of_bounds
        )
        self._platt = data.get("platt")
        self._isotonic = data.get("isotonic")
        self._fitted = bool(data.get("fitted", False))
        self.calibration_log = data.get("calibration_log", {})
        logger.info("ProbabilityCalibrator loaded from %s", path)
        return self
