import logging
import os
from typing import Any, Optional

import numpy as np

logger = logging.getLogger("ContinuousTraining")

CONTINUOUS_FEATURE_NAMES = [
    "close",
    "volume",
    "rsi",
    "macd",
    "bb_upper",
    "bb_lower",
    "ema_9",
    "ema_21",
    "atr",
]


def register_continuous_features(
    feature_registry: dict[str, Any],
    ticker: str,
    continuous_horizons: dict[str, int],
    feature_names: Optional[list[str]] = None,
    target_feature: str = "close",
    horizon: int = 3,
) -> None:
    fnames = feature_names or CONTINUOUS_FEATURE_NAMES
    feature_registry[ticker] = (fnames + [target_feature], target_feature)
    continuous_horizons[ticker] = horizon
    logger.info(
        "Registered %d continuous features for %s (target=%s, horizon=%d)",
        len(fnames), ticker, target_feature, horizon,
    )
