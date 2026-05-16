import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Any, Optional

import numpy as np
from sklearn.model_selection import TimeSeriesSplit

from utils.feature_store import FeatureStore
from utils.notifier import TelegramNotifier
import os

logger = logging.getLogger("TrainingPipeline")


MODEL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "user_data", "models"
)


class TrainingPipeline:
    def __init__(
        self,
        store: FeatureStore,
        model_dir: str = MODEL_DIR,
        retrain_interval_hours: int = 24,
        min_train_samples: int = 200,
        validation_split: float = 0.2,
    ) -> None:
        self.store = store
        self.model_dir = model_dir
        self.retrain_interval = retrain_interval_hours
        self.min_samples = min_train_samples
        self.validation_split = validation_split
        self._models: dict[str, Any] = {}
        self._feature_registry: dict[str, list[str]] = {}
        os.makedirs(self.model_dir, exist_ok=True)

    def register_features(
        self, ticker: str, feature_names: list[str], target_feature: str = "",
    ) -> None:
        self._feature_registry[ticker] = (feature_names, target_feature)
        logger.info(f"Registered {len(feature_names)} features for {ticker} (target={target_feature or 'last'})")

    def _build_training_set(
        self, ticker: str, feature_names: list[str], target_feature: str = "",
    ) -> Optional[tuple[np.ndarray, np.ndarray]]:
        series_list: list[np.ndarray] = []
        target_series: Optional[np.ndarray] = None
        for fname in feature_names:
            history = self.store.get_feature_history(ticker, fname)
            if len(history) < 10:
                logger.warning(f"Too few samples for {ticker}/{fname}: {len(history)}")
                return None
            vals = np.array([h["value"] for h in history], dtype=np.float32)
            if fname == target_feature:
                target_series = vals.copy()
            else:
                series_list.append(vals)

        if target_series is None:
            if len(series_list) < 2:
                return None
            target_series = series_list.pop()

        if not series_list or target_series is None:
            return None

        min_len = min(min(len(s) for s in series_list), len(target_series))
        X = np.column_stack([s[-min_len:] for s in series_list])
        target_series = target_series[-min_len:]

        horizon = max(1, len(X) // 20)
        horizon = min(horizon, 20)
        forward_returns = np.full(len(target_series), np.nan)
        for j in range(len(target_series) - horizon):
            forward_returns[j] = target_series[j + horizon] - target_series[j]
        valid = ~np.isnan(forward_returns)
        y = np.where(forward_returns[valid] > 0, 1, 0).astype(np.int32)
        X = X[valid]

        if len(X) < self.min_samples:
            logger.warning(f"Insufficient samples for {ticker}: {len(X)} < {self.min_samples}")
            return None

        return X, y

    def train(
        self,
        ticker: str,
        hyperparams: Optional[dict] = None,
        tft_checkpoint: Optional[str] = None,
    ) -> Optional[dict]:
        from user_data.freqaimodels.HybridQuantModel import (
            HybridQuantModel, TFTEmbeddingHook,
        )

        registered = self._feature_registry.get(ticker)
        if not registered:
            logger.warning(f"No features registered for {ticker}")
            return None
        feature_names, target_feature = registered if isinstance(registered, tuple) else (registered, "")

        train_data = self._build_training_set(ticker, feature_names, target_feature)
        if train_data is None:
            return None

        X, y = train_data

        split = int(len(X) * (1.0 - self.validation_split))
        X_train, X_val = X[:split], X[split:]
        y_train, y_val = y[:split], y[split:]

        if len(np.unique(y_train)) < 2:
            logger.warning(f"Training target has single class for {ticker}, skipping")
            return None

        tft_hook: Optional[TFTEmbeddingHook] = None
        if tft_checkpoint and os.path.exists(tft_checkpoint):
            tft_hook = TFTEmbeddingHook()
            tft_hook.load_tft(tft_checkpoint)

        params = hyperparams or {}
        model = HybridQuantModel(tft_hook=tft_hook, **params)
        model._feature_names = feature_names
        model.fit(X_train, y_train)

        train_acc = model.score(X_train, y_train)
        val_acc = model.score(X_val, y_val) if len(X_val) > 0 else 0.0

        meta_weights = model.get_meta_weights()
        feature_imp = model.feature_importance()

        model_path = os.path.join(self.model_dir, f"{ticker}_hybrid.pkl")
        model.save(model_path)

        result = {
            "ticker": ticker,
            "model_path": model_path,
            "train_samples": len(X_train),
            "val_samples": len(X_val),
            "train_accuracy": round(float(train_acc), 4),
            "val_accuracy": round(float(val_acc), 4),
            "meta_weights": meta_weights,
            "top_features": dict(
                sorted(feature_imp.items(), key=lambda x: -abs(x[1]))[:10]
            ),
            "timestamp": time.time(),
        }
        self._models[ticker] = model

        logger.info(
            f"Training complete for {ticker}: "
            f"train_acc={train_acc:.4f} val_acc={val_acc:.4f} "
            f"meta_weights={meta_weights}"
        )

        # Alert
        try:
            from core.container import ServiceContainer
            container = ServiceContainer.get_instance()
            if container.notifier:
                container.notifier.send(
                    f"🎓 *Model Trained: {ticker}*\n"
                    f"Train Accuracy: `{train_acc:.4f}`\n"
                    f"Val Accuracy: `{val_acc:.4f}`"
                )
        except Exception:
            pass

        return result

    def rolling_train(
        self,
        tickers: list[str],
        hyperparams: Optional[dict] = None,
        tft_checkpoint: Optional[str] = None,
    ) -> dict[str, Any]:
        results: dict[str, Any] = {}
        for ticker in tickers:
            try:
                result = self.train(ticker, hyperparams, tft_checkpoint)
                results[ticker] = result or {"status": "SKIPPED", "reason": "insufficient_data"}
            except Exception as e:
                logger.error(f"Training failed for {ticker}: {e}")
                results[ticker] = {"status": "ERROR", "error": str(e)}
        return results

    def predict(self, ticker: str, features: np.ndarray) -> Optional[dict]:
        model = self._models.get(ticker)
        if model is None:
            model_path = os.path.join(self.model_dir, f"{ticker}_hybrid.pkl")
            if os.path.exists(model_path):
                from user_data.freqaimodels.HybridQuantModel import HybridQuantModel
                model = HybridQuantModel().load(model_path)
                self._models[ticker] = model
            else:
                logger.warning(f"No model found for {ticker}")
                return None

        proba = model.predict_proba(features)
        direction = model.predict_direction(features)[0]
        return {
            "ticker": ticker,
            "prob_up": float(proba[0, 1]),
            "prob_down": float(proba[0, 0]),
            "direction": int(direction),
            "signal": "BUY" if direction == 1 else "SELL",
        }

    def latest_features_as_vector(
        self, ticker: str, max_history: int = 50
    ) -> Optional[np.ndarray]:
        registered = self._feature_registry.get(ticker)
        if not registered:
            return None
        feature_names, target_feature = registered if isinstance(registered, tuple) else (registered, "")
        series_list: list[np.ndarray] = []
        for fname in feature_names:
            if fname == target_feature:
                continue
            history = self.store.get_feature_history(
                ticker, fname, limit=max_history
            )
            if len(history) < 2:
                return None
            vals = np.array([h["value"] for h in history], dtype=np.float32)
            series_list.append(vals)
        min_len = min(len(s) for s in series_list)
        X = np.column_stack([s[-min_len:] for s in series_list])
        return X[-1:]

    def backtest_walk_forward(
        self,
        ticker: str,
        n_splits: int = 5,
        hyperparams: Optional[dict] = None,
    ) -> Optional[dict]:
        registered = self._feature_registry.get(ticker)
        if not registered:
            return None
        feature_names, target_feature = registered if isinstance(registered, tuple) else (registered, "")

        train_data = self._build_training_set(ticker, feature_names, target_feature)
        if train_data is None:
            return None

        X, y = train_data
        n = len(X)
        horizon = max(1, n // 20)
        horizon = min(horizon, 20)
        tscv = TimeSeriesSplit(n_splits=n_splits, gap=horizon)

        fold_metrics: list[dict] = []
        for i, (train_idx, val_idx) in enumerate(tscv.split(X)):
            X_train_fold = X[train_idx]
            y_train_fold = y[train_idx]
            X_val_fold = X[val_idx]
            y_val_fold = y[val_idx]

            if len(np.unique(y_train_fold)) < 2:
                continue

            from user_data.freqaimodels.HybridQuantModel import HybridQuantModel
            model = HybridQuantModel(**(hyperparams or {}))
            model._feature_names = feature_names
            model.fit(X_train_fold, y_train_fold)

            fold_acc = model.score(X_val_fold, y_val_fold)
            fold_metrics.append({
                "fold": i,
                "train_samples": len(X_train_fold),
                "val_samples": len(X_val_fold),
                "val_accuracy": round(float(fold_acc), 4),
            })

        if not fold_metrics:
            return None

        accuracies = [m["val_accuracy"] for m in fold_metrics]
        return {
            "ticker": ticker,
            "n_splits": len(fold_metrics),
            "fold_metrics": fold_metrics,
            "mean_val_accuracy": round(float(np.mean(accuracies)), 4),
            "std_val_accuracy": round(float(np.std(accuracies)), 4),
            "timestamp": time.time(),
        }

    def should_retrain(self, ticker: str) -> bool:
        model_path = os.path.join(self.model_dir, f"{ticker}_hybrid.pkl")
        if not os.path.exists(model_path):
            return True
        mtime = os.path.getmtime(model_path)
        elapsed = (time.time() - mtime) / 3600
        return elapsed >= self.retrain_interval

    def run_cycle(self, ticker: str) -> Optional[dict]:
        """Convenience method for health-check triggered retraining."""
        return self.train(ticker)

    def auto_retrain_if_needed(
        self,
        tickers: list[str],
        hyperparams: Optional[dict] = None,
        tft_checkpoint: Optional[str] = None,
    ) -> dict[str, Any]:
        results: dict[str, Any] = {}
        for ticker in tickers:
            if self.should_retrain(ticker):
                logger.info(f"Auto-retrain triggered for {ticker}")
                result = self.train(ticker, hyperparams, tft_checkpoint)
                results[ticker] = result or {"status": "SKIPPED"}
            else:
                results[ticker] = {"status": "SKIPPED", "reason": "within_retrain_interval"}
        return results

    def list_trained_models(self) -> list[dict]:
        models: list[dict] = []
        if not os.path.exists(self.model_dir):
            return models
        for f in os.listdir(self.model_dir):
            if f.endswith("_hybrid.pkl"):
                path = os.path.join(self.model_dir, f)
                ticker = f.replace("_hybrid.pkl", "")
                models.append({
                    "ticker": ticker,
                    "path": path,
                    "size_kb": round(os.path.getsize(path) / 1024, 1),
                    "mtime": datetime.fromtimestamp(os.path.getmtime(path)).isoformat(),
                })
        return models
