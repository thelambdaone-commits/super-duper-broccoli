import logging
import os
import time
from datetime import datetime
from typing import Any, Optional

import numpy as np
import pandas as pd
from sklearn.model_selection import TimeSeriesSplit

from core.calibration.metrics import (
    audit_model_calibration,
    calculate_dissimilarity_index,
)
from core.training.model_manager import (
    list_trained_models,
    prepare_prediction_input,
    prune_model_artifacts,
    should_retrain,
)
from core.training.prediction import (
    predict as _predict,
    latest_features_as_vector as _latest_features_as_vector,
)
from utils.feature_store import FeatureStore

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
        self._calibrated_models: dict[str, Any] = {}
        self._calibrators: dict[str, Any] = {}
        self._feature_registry: dict[str, list[str]] = {}
        os.makedirs(self.model_dir, exist_ok=True)

    def register_features(
        self, ticker: str, feature_names: list[str], target_feature: str = "",
    ) -> None:
        self._feature_registry[ticker] = (feature_names, target_feature)
        logger.info(f"Registered {len(feature_names)} features for {ticker} (target={target_feature or 'last'})")

    def _get_feature_history(
        self,
        ticker: str,
        feature_name: str,
        limit: int = 1000,
        until_ts: Optional[float] = None,
    ) -> list[dict]:
        try:
            return self.store.get_feature_history(
                ticker, feature_name, limit=limit, until_ts=until_ts
            )
        except TypeError:
            return self.store.get_feature_history(ticker, feature_name, limit=limit)

    @staticmethod
    def _as_float_rows(history: list[dict]) -> list[tuple[float, float]]:
        rows: list[tuple[float, float]] = []
        for row in history:
            try:
                ts = float(row["timestamp"])
                value = float(row["value"])
            except (KeyError, TypeError, ValueError):
                continue
            if np.isfinite(ts) and np.isfinite(value):
                rows.append((ts, value))
        return sorted(rows, key=lambda item: item[0])

    @staticmethod
    def _asof_value(rows: list[tuple[float, float]], ts: float, cursor: int) -> tuple[Optional[float], int]:
        while cursor + 1 < len(rows) and rows[cursor + 1][0] <= ts:
            cursor += 1
        if cursor < 0:
            return None, cursor
        return rows[cursor][1], cursor

    calculate_dissimilarity_index = staticmethod(calculate_dissimilarity_index)
    audit_model_calibration = staticmethod(audit_model_calibration)

    def _build_training_set(
        self, ticker: str, feature_names: list[str], target_feature: str = "",
    ) -> Optional[tuple[np.ndarray, np.ndarray, np.ndarray]]:
        target_name = target_feature or feature_names[-1]
        feature_columns = [name for name in feature_names if name != target_name]
        if not feature_columns:
            logger.warning(f"No explanatory features registered for {ticker}")
            return None

        target_rows = self._as_float_rows(self._get_feature_history(ticker, target_name))
        if len(target_rows) < 10:
            logger.warning(f"Too few samples for {ticker}/{target_name}: {len(target_rows)}")
            return None

        feature_rows: dict[str, list[tuple[float, float]]] = {}
        for fname in feature_columns:
            rows = self._as_float_rows(self._get_feature_history(ticker, fname))
            if len(rows) < 10:
                logger.warning(f"Too few samples for {ticker}/{fname}: {len(rows)}")
                return None
            feature_rows[fname] = rows

        cursors = {fname: -1 for fname in feature_columns}
        aligned_features: list[list[float]] = []
        aligned_target: list[float] = []
        aligned_ts: list[float] = []

        for ts, target_value in target_rows:
            row: list[float] = []
            complete = True
            for fname in feature_columns:
                value, cursors[fname] = self._asof_value(feature_rows[fname], ts, cursors[fname])
                if value is None:
                    complete = False
                    break
                row.append(value)
            if complete:
                aligned_features.append(row)
                aligned_target.append(target_value)
                aligned_ts.append(ts)

        if len(aligned_features) < 10:
            logger.warning(f"Insufficient point-in-time aligned rows for {ticker}: {len(aligned_features)}")
            return None

        X_all = np.asarray(aligned_features, dtype=np.float32)
        target_series = np.asarray(aligned_target, dtype=np.float32)
        timestamps = np.asarray(aligned_ts, dtype=np.float64)

        horizon = max(1, len(X_all) // 20)
        horizon = min(horizon, 20)
        valid_len = len(target_series) - horizon
        if valid_len <= 0:
            return None

        forward_returns = target_series[horizon:] - target_series[:-horizon]
        X = X_all[:valid_len]
        y = np.where(forward_returns > 0, 1, 0).astype(np.int32)
        sample_ts = timestamps[:valid_len]

        if len(X) < self.min_samples:
            logger.warning(f"Insufficient samples for {ticker}: {len(X)} < {self.min_samples}")
            return None

        return X, y, sample_ts

    def build_multi_market_frame(
        self,
        ticker: str,
        feature_names: list[str],
        target_feature: str = "",
        binance_symbol: str = "",
        since_ts: float = 0.0,
        limit: int = 5000,
        window_seconds: int = 300,
    ) -> list[dict]:
        base_rows = self.store.get_multi_market_feature_frame(
            target_ticker=ticker,
            base_feature_names=[name for name in feature_names if name != (target_feature or feature_names[-1])],
            binance_symbol=binance_symbol or ticker,
            since_ts=since_ts,
            limit=limit,
            window_seconds=window_seconds,
        )
        return base_rows

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
        target_name = target_feature or feature_names[-1]
        model_feature_names = [name for name in feature_names if name != target_name]

        train_data = self._build_training_set(ticker, feature_names, target_feature)
        if train_data is None:
            return None

        X, y, sample_ts = train_data

        split = int(len(X) * (1.0 - self.validation_split))
        X_train, X_val = X[:split], X[split:]
        y_train, y_val = y[:split], y[split:]
        train_ts, val_ts = sample_ts[:split], sample_ts[split:]

        if len(np.unique(y_train)) < 2:
            logger.warning(f"Training target has single class for {ticker}, skipping")
            return None

        tft_hook: Optional[TFTEmbeddingHook] = None
        if tft_checkpoint and os.path.exists(tft_checkpoint):
            tft_hook = TFTEmbeddingHook()
            tft_hook.load_tft(tft_checkpoint)

        params = hyperparams or {}
        model = HybridQuantModel(tft_hook=tft_hook, **params)
        model._feature_names = model_feature_names
        model.fit(X_train, y_train)
        model._training_mean = np.mean(X_train, axis=0)
        model._training_std = np.where(np.std(X_train, axis=0) < 1e-8, 1.0, np.std(X_train, axis=0))
        model._ood_di_threshold = float(os.getenv("OOD_DI_THRESHOLD", "3.0"))

        train_acc = model.score(X_train, y_train)
        val_acc = model.score(X_val, y_val) if len(X_val) > 0 else 0.0

        meta_weights = model.get_meta_weights()
        feature_imp = model.feature_importance()

        model_path = os.path.join(self.model_dir, f"{ticker}_hybrid.pkl")
        model.save(model_path)

        calibrator_path = os.path.join(self.model_dir, f"{ticker}_calibrator.pkl")
        calibration_log = None
        calibrated_path = ""
        if len(X_val) >= 10 and len(np.unique(y_val)) >= 2:
            try:
                from user_data.strategies.probability_calibrator import ProbabilityCalibrator

                calibrator = ProbabilityCalibrator(
                    fusion_mode=os.getenv("PREDICTION_CALIBRATION_MODE", "ensemble")
                )
                calibrator.calibrate(
                    model.predict_proba(X_val),
                    y_val,
                    ticker=ticker,
                    model_version=os.path.basename(model_path),
                )
                calibrator.save(calibrator_path)
                self._calibrators[ticker] = calibrator
                calibration_log = calibrator.calibration_log

                from user_data.freqaimodels.calibrated_bundle import CalibratedModelBundle
                import joblib

                bundle = CalibratedModelBundle(
                    base_model=model,
                    calibrator=calibrator,
                    calibration_log=calibration_log,
                )
                calibrated_path = os.path.join(self.model_dir, f"{ticker}_calibrated.pkl")
                joblib.dump(bundle, calibrated_path, compress=("xz", 3))
                self._calibrated_models[ticker] = bundle
            except Exception as e:
                logger.warning(f"Calibration persistence skipped for {ticker}: {e}")
            if calibrated_path:
                try:
                    model_for_audit = self._calibrated_models[ticker].predict_proba(X_val)
                    audit = self.audit_model_calibration(y_val, model_for_audit, n_bins=10)
                    if calibration_log is None:
                        calibration_log = {}
                    calibration_log["ece"] = audit["ece"]
                    calibration_log["calibration_curve"] = {
                        "true_frequencies": audit["true_frequencies"],
                        "pred_probabilities": audit["pred_probabilities"],
                        "n_bins": audit["n_bins"],
                    }
                except Exception as e:
                    logger.warning(f"Calibration audit skipped for {ticker}: {e}")

        result = {
            "ticker": ticker,
            "model_path": model_path,
            "calibrator_path": calibrator_path if os.path.exists(calibrator_path) else "",
            "calibrated_model_path": calibrated_path if calibrated_path and os.path.exists(calibrated_path) else "",
            "train_samples": len(X_train),
            "val_samples": len(X_val),
            "train_start_ts": float(train_ts[0]) if len(train_ts) else 0.0,
            "train_end_ts": float(train_ts[-1]) if len(train_ts) else 0.0,
            "val_start_ts": float(val_ts[0]) if len(val_ts) else 0.0,
            "val_end_ts": float(val_ts[-1]) if len(val_ts) else 0.0,
            "walk_forward_policy": "chronological_holdout_no_shuffle",
            "train_accuracy": round(float(train_acc), 4),
            "val_accuracy": round(float(val_acc), 4),
            "meta_weights": meta_weights,
            "top_features": dict(
                sorted(feature_imp.items(), key=lambda x: -abs(x[1]))[:10]
            ),
            "calibration_log": calibration_log or {},
            "timestamp": time.time(),
        }
        self._models[ticker] = model

        logger.info(
            f"Training complete for {ticker}: "
            f"train_acc={train_acc:.4f} val_acc={val_acc:.4f} "
            f"meta_weights={meta_weights}"
        )

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
        return _predict(
            ticker, features,
            model_dir=self.model_dir,
            models=self._models,
            calibrated_models=self._calibrated_models,
            calibrators=self._calibrators,
            store=self.store,
        )

    _prepare_prediction_input = staticmethod(prepare_prediction_input)

    def latest_features_as_vector(
        self, ticker: str, max_history: int = 50
    ) -> Optional[np.ndarray]:
        return _latest_features_as_vector(
            ticker, self._feature_registry, self.store, max_history=max_history,
        )

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

        X, y, sample_ts = train_data
        n = len(X)
        horizon = max(1, n // 20)
        horizon = min(horizon, 20)
        tscv = TimeSeriesSplit(n_splits=n_splits, gap=horizon)
        target_name = target_feature or feature_names[-1]
        model_feature_names = [name for name in feature_names if name != target_name]

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
            model._feature_names = model_feature_names
            model.fit(X_train_fold, y_train_fold)

            fold_acc = model.score(X_val_fold, y_val_fold)
            fold_metrics.append({
                "fold": i,
                "train_samples": len(X_train_fold),
                "val_samples": len(X_val_fold),
                "train_end_ts": float(sample_ts[train_idx[-1]]),
                "val_start_ts": float(sample_ts[val_idx[0]]),
                "gap_samples": int(val_idx[0] - train_idx[-1] - 1),
                "val_accuracy": round(float(fold_acc), 4),
            })

        if not fold_metrics:
            return None

        accuracies = [m["val_accuracy"] for m in fold_metrics]
        return {
            "ticker": ticker,
            "n_splits": len(fold_metrics),
            "partitioning": "walk_forward_timeseries_gap",
            "gap_samples": horizon,
            "fold_metrics": fold_metrics,
            "mean_val_accuracy": round(float(np.mean(accuracies)), 4),
            "std_val_accuracy": round(float(np.std(accuracies)), 4),
            "timestamp": time.time(),
        }

    def should_retrain(self, ticker: str) -> bool:
        return should_retrain(self.model_dir, ticker, self.retrain_interval)

    def run_cycle(self, ticker: str) -> Optional[dict]:
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
        return list_trained_models(self.model_dir)

    def prune_model_artifacts(self, ticker: str, keep_latest: int = 2) -> dict[str, int]:
        return prune_model_artifacts(self.model_dir, ticker)

    def update_calibration_from_paper_trades(
        self, ticker: str, ledger: Any
    ) -> Optional[dict]:
        """
        Dynamically update the probability calibrator using actual won/lost outcomes
        from simulated (paper) trades recorded in the SQLite Ledger.
        This forms the core online ML reinforcement loop.
        """
        cursor = ledger.conn.cursor()
        cursor.execute(
            "SELECT confidence, is_win FROM paper_positions "
            "WHERE ticker = ? AND status = 'CLOSED' AND is_win IS NOT NULL "
            "ORDER BY closed_at DESC",
            (ticker,),
        )
        rows = cursor.fetchall()
        if len(rows) < 10:
            logger.warning(
                f"Dynamic calibration requires at least 10 closed paper trades for {ticker}, got {len(rows)}"
            )
            return None

        # Build data arrays
        confidences = np.array([r["confidence"] for r in rows], dtype=np.float64)
        y_true = np.array([r["is_win"] for r in rows], dtype=np.int32)

        if len(np.unique(y_true)) < 2:
            logger.warning(
                f"Dynamic calibration requires both won and lost trades in outcomes for {ticker}, skipping"
            )
            return None

        # OOF probabilities are input as a 2D array of raw probabilities
        oof_proba = np.zeros((len(confidences), 2), dtype=np.float64)
        oof_proba[:, 1] = confidences
        oof_proba[:, 0] = 1.0 - confidences

        calibrator_path = os.path.join(self.model_dir, f"{ticker}_calibrator.pkl")

        try:
            from user_data.strategies.probability_calibrator import ProbabilityCalibrator

            calibrator = ProbabilityCalibrator(
                fusion_mode=os.getenv("PREDICTION_CALIBRATION_MODE", "ensemble")
            )
            calibrator.calibrate(
                oof_proba,
                y_true,
                store=self.store,
                ticker=ticker,
                model_version="online_reinforcement",
            )
            calibrator.save(calibrator_path)
            self._calibrators[ticker] = calibrator
            logger.info(
                f"Reinforcement calibration updated for {ticker} using {len(rows)} paper trade outcomes!"
            )
            return calibrator.calibration_log
        except Exception as e:
            logger.error(f"Failed dynamic reinforcement calibration for {ticker}: {e}")
            return None

    # ── Continuous market methods (additive, no Polymarket overlap) ──

    def register_continuous_features(
        self,
        ticker: str,
        feature_names: Optional[list[str]] = None,
        target_feature: str = "close",
        horizon: int = 3,
    ) -> None:
        from config.constants import CONTINUOUS_FEATURE_NAMES
        fnames = feature_names or CONTINUOUS_FEATURE_NAMES
        self._feature_registry[ticker] = (
            fnames + [target_feature],
            target_feature,
        )
        self._continuous_horizons: dict[str, int] = getattr(self, "_continuous_horizons", {})
        self._continuous_horizons[ticker] = horizon
        logger.info(
            f"Registered {len(fnames)} continuous features for {ticker} "
            f"(target={target_feature}, horizon={horizon})"
        )

    def _build_continuous_training_set(
        self,
        ticker: str,
        feature_names: list[str],
        target_feature: str = "close",
        horizon: int = 3,
    ) -> Optional[tuple[np.ndarray, np.ndarray, np.ndarray]]:
        target_name = target_feature
        feature_columns = [name for name in feature_names if name != target_name]
        if not feature_columns:
            logger.warning(f"No explanatory features registered for {ticker}")
            return None

        target_rows = self._as_float_rows(self._get_feature_history(ticker, target_name))
        if len(target_rows) < 10 + horizon:
            logger.warning(
                f"Too few continuous samples for {ticker}/{target_name}: "
                f"{len(target_rows)} (need >= {10 + horizon})"
            )
            return None

        feature_rows: dict[str, list[tuple[float, float]]] = {}
        for fname in feature_columns:
            rows = self._as_float_rows(self._get_feature_history(ticker, fname))
            if len(rows) < 10:
                logger.warning(f"Too few samples for {ticker}/{fname}: {len(rows)}")
                return None
            feature_rows[fname] = rows

        cursors = {fname: -1 for fname in feature_columns}
        aligned_features: list[list[float]] = []
        aligned_target: list[float] = []
        aligned_ts: list[float] = []

        for ts, target_value in target_rows:
            row: list[float] = []
            complete = True
            for fname in feature_columns:
                value, cursors[fname] = self._asof_value(feature_rows[fname], ts, cursors[fname])
                if value is None:
                    complete = False
                    break
                row.append(value)
            if complete:
                aligned_features.append(row)
                aligned_target.append(target_value)
                aligned_ts.append(ts)

        if len(aligned_features) < 10 + horizon:
            logger.warning(
                f"Insufficient aligned rows for continuous {ticker}: "
                f"{len(aligned_features)} (need >= {10 + horizon})"
            )
            return None

        X_all = np.asarray(aligned_features, dtype=np.float32)
        target_series = np.asarray(aligned_target, dtype=np.float32)
        timestamps = np.asarray(aligned_ts, dtype=np.float64)

        valid_len = len(target_series) - horizon
        if valid_len <= 0:
            return None

        future_prices = target_series[horizon:]
        current_prices = target_series[:valid_len]
        direction = np.where(future_prices > current_prices, 1, 0).astype(np.int32)

        X = X_all[:valid_len]
        y = direction
        sample_ts = timestamps[:valid_len]

        if len(X) < self.min_samples:
            logger.warning(
                f"Insufficient continuous samples for {ticker}: "
                f"{len(X)} < {self.min_samples}"
            )
            return None

        return X, y, sample_ts

    def train_continuous(
        self,
        ticker: str,
        hyperparams: Optional[dict] = None,
        horizon: Optional[int] = None,
        tft_checkpoint: Optional[str] = None,
    ) -> Optional[dict]:
        from user_data.freqaimodels.HybridQuantModel import (
            HybridQuantModel, TFTEmbeddingHook,
        )

        registered = self._feature_registry.get(ticker)
        if not registered:
            logger.warning(f"No features registered for continuous {ticker}")
            return None
        feature_names, target_feature = registered if isinstance(registered, tuple) else (registered, "")
        target_name = target_feature or "close"
        model_feature_names = [name for name in feature_names if name != target_name]

        horizons: dict[str, int] = getattr(self, "_continuous_horizons", {})
        h = horizon or horizons.get(ticker, 3)

        train_data = self._build_continuous_training_set(
            ticker, feature_names, target_feature, horizon=h,
        )
        if train_data is None:
            return None

        X, y, sample_ts = train_data

        split = int(len(X) * (1.0 - self.validation_split))
        X_train, X_val = X[:split], X[split:]
        y_train, y_val = y[:split], y[split:]
        train_ts, val_ts = sample_ts[:split], sample_ts[split:]

        if len(np.unique(y_train)) < 2:
            logger.warning(f"Continuous training target has single class for {ticker}, skipping")
            return None

        tft_hook: Optional[TFTEmbeddingHook] = None
        if tft_checkpoint and os.path.exists(tft_checkpoint):
            tft_hook = TFTEmbeddingHook()
            tft_hook.load_tft(tft_checkpoint)

        params = hyperparams or {}
        model = HybridQuantModel(tft_hook=tft_hook, **params)
        model._feature_names = model_feature_names
        model.fit(X_train, y_train)
        model._training_mean = np.mean(X_train, axis=0)
        model._training_std = np.where(np.std(X_train, axis=0) < 1e-8, 1.0, np.std(X_train, axis=0))
        model._ood_di_threshold = float(os.getenv("OOD_DI_THRESHOLD", "3.0"))

        train_acc = model.score(X_train, y_train)
        val_acc = model.score(X_val, y_val) if len(X_val) > 0 else 0.0

        meta_weights = model.get_meta_weights()
        feature_imp = model.feature_importance()

        model_path = os.path.join(self.model_dir, f"{ticker}_continuous_hybrid.pkl")
        model.save(model_path)

        calibrator_path = os.path.join(self.model_dir, f"{ticker}_continuous_calibrator.pkl")
        calibration_log = None
        calibrated_path = ""
        if len(X_val) >= 10 and len(np.unique(y_val)) >= 2:
            try:
                from user_data.strategies.probability_calibrator import ProbabilityCalibrator

                calibrator = ProbabilityCalibrator(
                    fusion_mode=os.getenv("PREDICTION_CALIBRATION_MODE", "ensemble")
                )
                calibrator.calibrate(
                    model.predict_proba(X_val),
                    y_val,
                    ticker=ticker,
                    model_version=os.path.basename(model_path),
                )
                calibrator.save(calibrator_path)
                self._calibrators[ticker] = calibrator
                calibration_log = calibrator.calibration_log

                from user_data.freqaimodels.calibrated_bundle import CalibratedModelBundle
                import joblib as _jl

                bundle = CalibratedModelBundle(
                    base_model=model,
                    calibrator=calibrator,
                    calibration_log=calibration_log,
                )
                calibrated_path = os.path.join(self.model_dir, f"{ticker}_continuous_calibrated.pkl")
                _jl.dump(bundle, calibrated_path, compress=("xz", 3))
                self._calibrated_models[ticker] = bundle
            except Exception as e:
                logger.warning(f"Continuous calibration skipped for {ticker}: {e}")
            if calibrated_path:
                try:
                    model_for_audit = self._calibrated_models[ticker].predict_proba(X_val)
                    audit = self.audit_model_calibration(y_val, model_for_audit, n_bins=10)
                    if calibration_log is None:
                        calibration_log = {}
                    calibration_log["ece"] = audit["ece"]
                    calibration_log["calibration_curve"] = {
                        "true_frequencies": audit["true_frequencies"],
                        "pred_probabilities": audit["pred_probabilities"],
                        "n_bins": audit["n_bins"],
                    }
                except Exception as e:
                    logger.warning(f"Continuous calibration audit skipped for {ticker}: {e}")

        result = {
            "ticker": ticker,
            "market_type": "continuous",
            "horizon": h,
            "model_path": model_path,
            "calibrator_path": calibrator_path if os.path.exists(calibrator_path) else "",
            "calibrated_model_path": calibrated_path if calibrated_path and os.path.exists(calibrated_path) else "",
            "train_samples": len(X_train),
            "val_samples": len(X_val),
            "train_start_ts": float(train_ts[0]) if len(train_ts) else 0.0,
            "train_end_ts": float(train_ts[-1]) if len(train_ts) else 0.0,
            "val_start_ts": float(val_ts[0]) if len(val_ts) else 0.0,
            "val_end_ts": float(val_ts[-1]) if len(val_ts) else 0.0,
            "walk_forward_policy": "chronological_holdout_no_shuffle",
            "train_accuracy": round(float(train_acc), 4),
            "val_accuracy": round(float(val_acc), 4),
            "meta_weights": meta_weights,
            "top_features": dict(
                sorted(feature_imp.items(), key=lambda x: -abs(x[1]))[:10]
            ),
            "calibration_log": calibration_log or {},
            "timestamp": time.time(),
        }
        self._models[ticker] = model

        logger.info(
            f"Continuous training complete for {ticker}: "
            f"train_acc={train_acc:.4f} val_acc={val_acc:.4f} "
            f"meta_weights={meta_weights} horizon={h}"
        )
        return result

    def rolling_train_continuous(
        self,
        tickers: list[str],
        hyperparams: Optional[dict] = None,
        horizon: Optional[int] = None,
        tft_checkpoint: Optional[str] = None,
    ) -> dict[str, Any]:
        results: dict[str, Any] = {}
        for ticker in tickers:
            try:
                result = self.train_continuous(ticker, hyperparams, horizon, tft_checkpoint)
                results[ticker] = result or {"status": "SKIPPED", "reason": "insufficient_data"}
            except Exception as e:
                logger.error(f"Continuous training failed for {ticker}: {e}")
                results[ticker] = {"status": "ERROR", "error": str(e)}
        return results

    def predict_continuous(self, ticker: str, features: np.ndarray) -> Optional[dict]:
        return self.predict(ticker, features)

    def backtest_walk_forward_continuous(
        self,
        ticker: str,
        n_splits: int = 5,
        hyperparams: Optional[dict] = None,
        horizon: Optional[int] = None,
    ) -> Optional[dict]:
        registered = self._feature_registry.get(ticker)
        if not registered:
            return None
        feature_names, target_feature = registered if isinstance(registered, tuple) else (registered, "")
        horizons: dict[str, int] = getattr(self, "_continuous_horizons", {})
        h = horizon or horizons.get(ticker, 3)

        train_data = self._build_continuous_training_set(
            ticker, feature_names, target_feature, horizon=h,
        )
        if train_data is None:
            return None

        X, y, sample_ts = train_data
        n = len(X)
        tscv = TimeSeriesSplit(n_splits=n_splits, gap=h)
        model_feature_names = [name for name in feature_names if name != (target_feature or "close")]

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
            model._feature_names = model_feature_names
            model.fit(X_train_fold, y_train_fold)

            fold_acc = model.score(X_val_fold, y_val_fold)
            fold_metrics.append({
                "fold": i,
                "train_samples": len(X_train_fold),
                "val_samples": len(X_val_fold),
                "horizon": h,
                "train_end_ts": float(sample_ts[train_idx[-1]]),
                "val_start_ts": float(sample_ts[val_idx[0]]),
                "gap_samples": int(val_idx[0] - train_idx[-1] - 1),
                "val_accuracy": round(float(fold_acc), 4),
            })

        if not fold_metrics:
            return None

        accuracies = [m["val_accuracy"] for m in fold_metrics]
        return {
            "ticker": ticker,
            "market_type": "continuous",
            "horizon": h,
            "n_splits": len(fold_metrics),
            "partitioning": "walk_forward_timeseries_gap",
            "gap_samples": h,
            "fold_metrics": fold_metrics,
            "mean_val_accuracy": round(float(np.mean(accuracies)), 4),
            "std_val_accuracy": round(float(np.std(accuracies)), 4),
            "timestamp": time.time(),
        }
