import logging
from typing import Optional

import numpy as np

from config.constants import REGIME_LOW_VOLATILITY

logger = logging.getLogger("RegimeUtils")


def get_regime_label(hmm: Optional[object], ticker: str) -> str:
    if hmm is None:
        return REGIME_LOW_VOLATILITY
    if not getattr(hmm, "_fitted", False):
        return REGIME_LOW_VOLATILITY
    zeros = np.zeros(100, dtype=np.float32)
    _, label = hmm.predict_with_label(zeros)
    return label
