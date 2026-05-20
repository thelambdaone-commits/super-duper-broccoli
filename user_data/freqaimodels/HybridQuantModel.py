import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import joblib
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from xgboost import XGBClassifier

logger = logging.getLogger("HybridQuantModel")

try:
    import torch
    HAS_TORCH = True
except ImportError:  # pragma: no cover - exercised by adapter behavior
    torch = None
    HAS_TORCH = False


MODEL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "user_data", "models"
)


@dataclass(frozen=True)
class UnifiedScoringOutput:
    market_id: str
    ml_calibrated_score: float
    estimated_edge: float
    is_fallback: bool
    ood_alert: bool = False
    dissimilarity_index: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_tradable(self, min_edge: float) -> bool:
        min_edge = float(min_edge)
        required_edge = min_edge * 1.5 if self.is_fallback else min_edge
        return self.estimated_edge >= required_edge and not self.ood_alert

    def to_signal_fields(self) -> dict[str, Any]:
        return {
            "predictive_probability": self.ml_calibrated_score,
            "predictive_edge": self.estimated_edge,
            "is_fallback": self.is_fallback,
            "ood_alert": self.ood_alert,
            "dissimilarity_index": self.dissimilarity_index,
        }


class TFTEmbeddingHook:
    def __init__(self, d_model: int = 128) -> None:
        self.d_model = d_model
        self._model: Any = None

    def load_tft(self, checkpoint_path: str) -> bool:
        try:
            from user_data.hypernetworks.tft_layers import TemporalFusionTransformer
            if not HAS_TORCH:
                logger.warning("TFT load skipped: torch is not installed")
                return False
            self._model = TemporalFusionTransformer(
                d_features=self.d_model, d_model=self.d_model
            )
            state = torch.load(checkpoint_path, map_location=torch.device("cpu"), weights_only=True)
            self._model.load_state_dict(state)
            self._model.eval()
            logger.info(f"TFT loaded from {checkpoint_path}")
            return True
        except Exception as e:
            logger.warning(f"TFT load failed (non-blocking): {e}")
            return False

    def extract_embeddings(self, X: np.ndarray) -> np.ndarray:
        if self._model is None:
            return X
        try:
            with torch.no_grad():
                x_t = torch.tensor(X, dtype=torch.float32).unsqueeze(1)
                _ = self._model(x_t)
                embeddings = self._model.grn(
                    self._model.lstm(self._model.input_proj(x_t))[0]
                )
                return embeddings[:, -1, :].numpy()
        except Exception as e:
            logger.warning(f"TFT embedding extraction failed: {e}")
            return X


class HybridQuantModelAdapter:
    """
    Optional CPU-first tensor scoring adapter.

    Runtime risk remains scalar; this adapter only produces normalized scoring
    fields and falls back to deterministic NumPy when tensor inference is unsafe.
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        model: Any = None,
        expected_features: Optional[int] = None,
        ood_threshold: float = 0.85,
    ) -> None:
        self.has_torch = HAS_TORCH
        self.model = model
        self.expected_features = expected_features
        self.ood_threshold = float(ood_threshold)
        if self.has_torch and model_path:
            self._load_tensor_model(model_path)

    def _load_tensor_model(self, path: str) -> None:
        try:
            self.model = torch.jit.load(path, map_location=torch.device("cpu"))
            self.model.eval()
            logger.info("Tensor scoring model loaded on CPU: %s", path)
        except Exception as e:
            logger.warning("Tensor model load failed; using deterministic fallback: %s", e)
            self.model = None

    def score_market(self, live_features: dict[str, Any], current_odds: float) -> UnifiedScoringOutput:
        if self.has_torch and self.model is not None:
            try:
                return self._execute_tensor_path(live_features, current_odds)
            except Exception as tensor_err:
                logger.warning(
                    "Tensor scoring failed; using deterministic fallback: %s",
                    tensor_err,
                )
        return self._execute_deterministic_fallback(live_features, current_odds)

    def _execute_tensor_path(
        self,
        features: dict[str, Any],
        current_odds: float,
    ) -> UnifiedScoringOutput:
        raw_vector = np.asarray(features.get("microstructure_vector", []), dtype=np.float32)
        raw_vector = np.ravel(raw_vector)
        if raw_vector.size == 0:
            raise ValueError("empty microstructure_vector")
        if self.expected_features is not None and raw_vector.size != self.expected_features:
            raise ValueError(f"expected {self.expected_features} features, got {raw_vector.size}")
        if not np.all(np.isfinite(raw_vector)):
            raise ValueError("microstructure_vector contains NaN or Inf")

        feat_tensor = torch.from_numpy(raw_vector).to(torch.float32).unsqueeze(0)
        with torch.no_grad():
            model_output = self.model(feat_tensor)
        out = model_output.detach().cpu().numpy() if hasattr(model_output, "detach") else np.asarray(model_output)
        out = np.ravel(out).astype(np.float64)
        if out.size == 0 or not np.all(np.isfinite(out)):
            raise ValueError("tensor model output is empty or non-finite")

        pred_score = float(np.clip(out[0], 0.0, 1.0))
        dissimilarity = float(out[1]) if out.size > 1 else 0.0
        edge = pred_score - float(current_odds)
        return UnifiedScoringOutput(
            market_id=str(features.get("market_id", "unknown")),
            ml_calibrated_score=pred_score,
            estimated_edge=edge,
            is_fallback=False,
            ood_alert=dissimilarity > self.ood_threshold,
            dissimilarity_index=dissimilarity,
            metadata={"path": "tensor"},
        )

    def _execute_deterministic_fallback(
        self,
        features: dict[str, Any],
        current_odds: float,
    ) -> UnifiedScoringOutput:
        history = np.asarray(features.get("historical_closes", [current_odds]), dtype=np.float64)
        history = history[np.isfinite(history)]
        fallback_score = float(current_odds) if history.size == 0 else float(np.clip(np.mean(history), 0.0, 1.0))
        return UnifiedScoringOutput(
            market_id=str(features.get("market_id", "unknown")),
            ml_calibrated_score=fallback_score,
            estimated_edge=fallback_score - float(current_odds),
            is_fallback=True,
            ood_alert=False,
            metadata={"path": "deterministic_fallback"},
        )


class HybridQuantModel(BaseEstimator, ClassifierMixin):
    def __init__(
        self,
        n_estimators: int = 100,
        max_depth: int = 5,
        learning_rate: float = 0.05,
        meta_learner: str = "logistic",
        random_state: int = 42,
        tft_hook: Optional[TFTEmbeddingHook] = None,
    ) -> None:
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.learning_rate = learning_rate
        self.random_state = random_state
        self._models: dict[str, Any] = {}
        self._meta: Any = None
        self._classes: Optional[np.ndarray] = None
        self._feature_names: list[str] = []
        self._tft_hook = tft_hook

        self._meta_type = meta_learner

    def _init_learners(self) -> None:
        common = {
            "n_estimators": self.n_estimators,
            "max_depth": self.max_depth,
            "random_state": self.random_state,
            "n_jobs": -1,
        }
        self._models = {
            "xgb": XGBClassifier(
                learning_rate=self.learning_rate,
                verbosity=0,
                **common,
            ),
            "lgbm": LGBMClassifier(
                learning_rate=self.learning_rate,
                verbosity=-1,
                min_child_samples=5,
                **common,
            ),
            "rf": RandomForestClassifier(**common),
        }

    def fit(self, X: np.ndarray, y: np.ndarray) -> "HybridQuantModel":
        self._classes = np.unique(y)
        self.classes_ = self._classes
        self._init_learners()

        X = self._ensure_feature_frame(X)
        if self._tft_hook is not None:
            X = self._tft_hook.extract_embeddings(np.asarray(X))

        for name, model in self._models.items():
            model.fit(X, y)
            logger.debug("%s trained", name)

        meta_X = np.column_stack([
            model.predict_proba(X)[:, 1] for model in self._models.values()
        ])

        if self._meta_type == "logistic":
            self._meta = LogisticRegression(random_state=self.random_state)
        else:
            self._meta = LogisticRegression(random_state=self.random_state)
        self._meta.fit(meta_X, y)

        logger.info(
            "HybridQuantModel trained -- base: %s meta: %s",
            list(self._models.keys()),
            self._meta_type,
        )
        self.is_fitted_ = True
        return self

    def __sklearn_is_fitted__(self) -> bool:
        return bool(getattr(self, "is_fitted_", False) and self._meta is not None and self._models)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if not self._models or self._meta is None:
            raise RuntimeError("Model not fitted. Call fit() first.")

        X = self._ensure_feature_frame(X)
        if self._tft_hook is not None:
            X = self._tft_hook.extract_embeddings(np.asarray(X))

        meta_X = np.column_stack([
            model.predict_proba(X)[:, 1] for model in self._models.values()
        ])
        return self._meta.predict_proba(meta_X)

    def predict(self, X: np.ndarray) -> np.ndarray:
        proba = self.predict_proba(X)
        return (proba[:, 1] >= 0.5).astype(np.int32)

    def predict_direction(self, X: np.ndarray, threshold: float = 0.5) -> np.ndarray:
        proba = self.predict_proba(X)
        return np.where(proba[:, 1] >= threshold, 1, -1)

    def score(self, X: np.ndarray, y: np.ndarray) -> float:
        from sklearn.metrics import accuracy_score
        return float(accuracy_score(y, self.predict(X)))

    def _ensure_feature_frame(self, X: np.ndarray) -> Any:
        if isinstance(X, pd.DataFrame):
            if self._feature_names and list(X.columns) != self._feature_names and len(self._feature_names) == X.shape[1]:
                return X.copy().set_axis(self._feature_names, axis=1)
            return X

        arr = np.asarray(X)
        if arr.ndim == 2 and self._feature_names and arr.shape[1] == len(self._feature_names):
            return pd.DataFrame(arr, columns=self._feature_names)
        return arr

    def feature_importance(self) -> dict[str, float]:
        if not self._models:
            return {}
        importance: dict[str, float] = {}
        for name, model in self._models.items():
            if hasattr(model, "feature_importances_"):
                imp = model.feature_importances_
                imp_sum = float(imp.sum())
                for i, val in enumerate(imp):
                    fname = self._feature_names[i] if i < len(self._feature_names) else f"f_{i}"
                    importance[f"{name}_{fname}"] = float(val) / imp_sum if imp_sum > 0 else 0.0
        return importance

    def get_meta_weights(self) -> dict[str, float]:
        if self._meta is None:
            return {}
        names = list(self._models.keys())
        weights = self._meta.coef_[0] if hasattr(self._meta, "coef_") else []
        return {names[i]: float(w) for i, w in enumerate(weights)} if len(weights) == len(names) else {}

    def save(self, path: str) -> str:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            prefix=f".{os.path.basename(path)}.",
            suffix=".tmp",
            dir=os.path.dirname(path),
        )
        with os.fdopen(fd, "wb") as f:
            joblib.dump({
                "models": self._models,
                "meta": self._meta,
                "classes": self._classes,
                "feature_names": self._feature_names,
                "config": {
                    "n_estimators": self.n_estimators,
                    "max_depth": self.max_depth,
                    "learning_rate": self.learning_rate,
                    "random_state": self.random_state,
                    "meta_type": self._meta_type,
                },
            }, f, compress=("xz", 3))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
        logger.info(f"Model saved to {path}")
        return path

    def load(self, path: str) -> "HybridQuantModel":
        data = joblib.load(path)
        self._models = data.get("models", {})
        self._meta = data.get("meta")
        self._classes = data.get("classes", np.array([0, 1]))
        self.classes_ = self._classes
        self._feature_names = data.get("feature_names", [])
        cfg = data.get("config", {})
        self.n_estimators = cfg.get("n_estimators", self.n_estimators)
        self.max_depth = cfg.get("max_depth", self.max_depth)
        self.learning_rate = cfg.get("learning_rate", self.learning_rate)
        self.random_state = cfg.get("random_state", self.random_state)
        self._meta_type = cfg.get("meta_type", self._meta_type)
        self.is_fitted_ = True
        logger.info(f"Model loaded from {path}")
        return self

    def summary(self) -> dict:
        meta_weights = self.get_meta_weights()
        return {
            "model_type": "HybridQuantModel",
            "base_learners": list(self._models.keys()),
            "meta_learner": self._meta_type,
            "meta_weights": meta_weights,
            "n_estimators": self.n_estimators,
            "max_depth": self.max_depth,
            "learning_rate": self.learning_rate,
            "n_features": len(self._feature_names) if self._feature_names else 0,
            "tft_enabled": self._tft_hook is not None and self._tft_hook._model is not None,
        }


def train_model_from_store(
    store,
    ticker: str,
    feature_names: list[str],
    target_col: str = "returns_direction",
    min_samples: int = 100,
    model_path: Optional[str] = None,
    tft_hook: Optional[TFTEmbeddingHook] = None,
    **kwargs,
) -> Optional[HybridQuantModel]:
    all_features: list[np.ndarray] = []
    all_targets: list[np.ndarray] = []

    for fname in feature_names:
        history = store.get_feature_history(ticker, fname)
        if len(history) >= min_samples:
            vals = np.array([h["value"] for h in history], dtype=np.float32)
            all_features.append(vals)

    if len(all_features) < 2:
        logger.warning(f"Not enough features for {ticker} (need >=2, got {len(all_features)})")
        return None

    X = np.column_stack(all_features)
    returns = X[:, -1] if X.shape[1] > 1 else X[:, 0]
    y = np.where(np.diff(returns, prepend=returns[0]) > 0, 1, 0).astype(np.int32)

    if len(y) < min_samples:
        logger.warning(f"Not enough samples for {ticker} ({len(y)} < {min_samples})")
        return None

    model = HybridQuantModel(tft_hook=tft_hook, **kwargs)
    model._feature_names = feature_names
    model.fit(X, y)

    if model_path:
        model.save(model_path)

    return model
