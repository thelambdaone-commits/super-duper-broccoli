from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass
class CalibratedModelBundle:
    base_model: Any
    calibrator: Any
    calibration_log: dict[str, Any]

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        raw = self.base_model.predict_proba(X)
        if self.calibrator is None:
            return raw
        return self.calibrator.predict_proba(raw)

    def predict(self, X: np.ndarray) -> np.ndarray:
        proba = self.predict_proba(X)
        return (proba[:, 1] >= 0.5).astype(np.int32)
