import logging
import os
import time
from datetime import datetime
from typing import Any, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("ModelManager")


def should_retrain(model_dir: str, ticker: str, retrain_interval_hours: int) -> bool:
    model_path = os.path.join(model_dir, f"{ticker}_hybrid.pkl")
    if not os.path.exists(model_path):
        return True
    mtime = os.path.getmtime(model_path)
    elapsed = (time.time() - mtime) / 3600
    return elapsed >= retrain_interval_hours


def list_trained_models(model_dir: str) -> list[dict]:
    models: list[dict] = []
    if not os.path.exists(model_dir):
        return models
    for f in os.listdir(model_dir):
        if f.endswith("_hybrid.pkl"):
            path = os.path.join(model_dir, f)
            ticker = f.replace("_hybrid.pkl", "")
            models.append({
                "ticker": ticker,
                "path": path,
                "size_kb": round(os.path.getsize(path) / 1024, 1),
                "mtime": datetime.fromtimestamp(os.path.getmtime(path)).isoformat(),
            })
    return models


def prune_model_artifacts(model_dir: str, ticker: str) -> dict[str, int]:
    removed = 0
    candidates: list[tuple[float, str]] = []
    if os.path.exists(model_dir):
        for fname in os.listdir(model_dir):
            if fname.startswith(f"{ticker}_") and fname.endswith(".pkl"):
                path = os.path.join(model_dir, fname)
                candidates.append((os.path.getmtime(path), path))

    candidates.sort(key=lambda item: item[0], reverse=True)
    keep_paths = set()
    for suffix in ("_hybrid.pkl", "_calibrated.pkl", "_calibrator.pkl"):
        path = os.path.join(model_dir, f"{ticker}{suffix}")
        if os.path.exists(path):
            keep_paths.add(path)

    for _, path in candidates:
        try:
            if path in keep_paths:
                continue
            os.remove(path)
            removed += 1
        except FileNotFoundError:
            continue
        except Exception as exc:
            logger.warning("Failed to prune model artifact %s: %s", path, exc)

    return {"removed": removed, "kept": len(keep_paths)}


def prepare_prediction_input(model: Any, features: np.ndarray) -> Any:
    feature_names = list(getattr(model, "_feature_names", []) or [])
    if isinstance(features, pd.DataFrame):
        if feature_names and list(features.columns) != feature_names and len(feature_names) == features.shape[1]:
            return features.copy().set_axis(feature_names, axis=1)
        return features

    arr = np.asarray(features)
    if arr.ndim == 2 and feature_names and arr.shape[1] == len(feature_names):
        return pd.DataFrame(arr, columns=feature_names)
    return arr
