from __future__ import annotations

import logging
import os
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np

from core.training_pipeline import TrainingPipeline
from utils.data_ingestion import _compute_technicals


logger = logging.getLogger("BTCDirectionLaunch")


DEFAULT_FEATURES = [
    "open",
    "high",
    "low",
    "volume",
    "rsi_14",
    "macd",
    "macd_signal",
    "bb_upper",
    "bb_lower",
    "log_return_1",
    "log_return_3",
    "log_return_5",
    "spread_bps",
    "order_imbalance",
    "close",
]


TRAINING_VARIANTS = [
    {"name": "balanced", "params": {"n_estimators": 80, "max_depth": 4, "learning_rate": 0.05}},
    {"name": "fast_reactive", "params": {"n_estimators": 120, "max_depth": 3, "learning_rate": 0.08}},
    {"name": "deeper_context", "params": {"n_estimators": 140, "max_depth": 6, "learning_rate": 0.03}},
]


@dataclass
class LaunchResult:
    interval: str
    requested_direction: str
    strongest_direction: str
    strongest_probability: float
    prob_up: float
    prob_down: float
    best_variant: str
    best_val_accuracy: float
    train_samples: int
    val_samples: int
    generated_at: float


class _MemoryFeatureStore:
    def __init__(self) -> None:
        self._data: dict[str, list[dict[str, float]]] = {}

    def add_history(self, ticker: str, fname: str, values: list[float], timestamps: list[float]) -> None:
        self._data[f"{ticker}_{fname}"] = [
            {"value": float(v), "timestamp": float(ts)}
            for ts, v in zip(timestamps, values)
        ]

    def get_feature_history(self, ticker: str, fname: str, limit: int = 1000):
        return self._data.get(f"{ticker}_{fname}", [])[-limit:]


class BTCDirectionLaunchService:
    def __init__(self, base_model_dir: Optional[str] = None, cache_ttl_seconds: Optional[dict[str, int]] = None) -> None:
        self.base_model_dir = base_model_dir or os.path.join(
            os.getenv(
                "RUNTIME_PATH",
                os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "runtime"),
            ),
            "user_data",
            "models",
            "btc_launch",
        )
        os.makedirs(self.base_model_dir, exist_ok=True)
        self.cache_ttl_seconds = cache_ttl_seconds or {"5m": 240, "15m": 600}
        self._cache: dict[str, LaunchResult] = {}
        self._cache_lock = threading.Lock()
        self.auto_train_enabled = str(os.getenv("BTC_LAUNCH_AUTO_TRAIN", "false")).strip().lower() in {"1", "true", "yes", "on"}

    def _history_period(self, interval: str) -> str:
        if interval == "5m":
            return "10d"
        if interval == "15m":
            return "30d"
        return "30d"

    def _fetch_btc_frame(self, interval: str):
        import pandas as pd
        import yfinance as yf

        period = self._history_period(interval)
        df = yf.Ticker("BTC-USD").history(period=period, interval=interval)
        if df is None or df.empty:
            raise ValueError(f"No BTC data returned for interval {interval}")

        df = df.rename(
            columns={
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
            }
        )
        df = df[["open", "high", "low", "close", "volume"]].copy()
        df = _compute_technicals(df)
        if not isinstance(df.index, pd.DatetimeIndex):
            raise ValueError("BTC frame has no DatetimeIndex")
        return df

    def _build_store(self, df, ticker_key: str) -> _MemoryFeatureStore:
        store = _MemoryFeatureStore()
        timestamps = [float(ts.timestamp()) for ts in df.index.to_pydatetime()]
        for feature_name in DEFAULT_FEATURES:
            values = df[feature_name].astype(float).tolist()
            store.add_history(ticker_key, feature_name, values, timestamps)
        return store

    def _train_variant(self, interval: str, variant: dict[str, Any]) -> tuple[TrainingPipeline, dict[str, Any]]:
        ticker_key = f"BTC_{interval}"
        df = self._fetch_btc_frame(interval)
        store = self._build_store(df, ticker_key)
        model_dir = tempfile.mkdtemp(prefix=f"btc_launch_{interval}_", dir=self.base_model_dir)
        pipeline = TrainingPipeline(
            store=store,
            model_dir=model_dir,
            retrain_interval_hours=1,
            min_train_samples=80,
            validation_split=0.2,
        )
        pipeline.register_features(ticker_key, DEFAULT_FEATURES, target_feature="close")
        result = pipeline.train(ticker_key, hyperparams=variant["params"])
        if result is None:
            raise ValueError(f"Training returned no result for variant {variant['name']}")
        result["variant_name"] = variant["name"]
        return pipeline, result

    def _with_requested_direction(self, result: LaunchResult, requested_direction: str) -> LaunchResult:
        return LaunchResult(
            interval=result.interval,
            requested_direction=requested_direction.lower(),
            strongest_direction=result.strongest_direction,
            strongest_probability=result.strongest_probability,
            prob_up=result.prob_up,
            prob_down=result.prob_down,
            best_variant=result.best_variant,
            best_val_accuracy=result.best_val_accuracy,
            train_samples=result.train_samples,
            val_samples=result.val_samples,
            generated_at=result.generated_at,
        )

    def get_cached(self, interval: str, requested_direction: str = "up") -> Optional[LaunchResult]:
        ttl = int(self.cache_ttl_seconds.get(interval, 0) or 0)
        with self._cache_lock:
            result = self._cache.get(interval)
        if result is None:
            return None
        if ttl > 0 and (time.time() - result.generated_at) > ttl:
            return None
        return self._with_requested_direction(result, requested_direction)

    def get_cached_stale(self, interval: str, requested_direction: str = "up") -> Optional[LaunchResult]:
        with self._cache_lock:
            result = self._cache.get(interval)
        if result is None:
            return None
        return self._with_requested_direction(result, requested_direction)

    def _fallback_result(self, interval: str, requested_direction: str, *, reason: str = "fallback") -> LaunchResult:
        strongest_direction = requested_direction if requested_direction in {"up", "down"} else "up"
        prob_up = 0.5
        prob_down = 0.5
        if strongest_direction == "down":
            prob_up, prob_down = prob_down, prob_up
        logger.warning("BTC launch fallback used for %s (%s): %s", interval, requested_direction, reason)
        return LaunchResult(
            interval=interval,
            requested_direction=requested_direction,
            strongest_direction=strongest_direction,
            strongest_probability=0.5,
            prob_up=prob_up,
            prob_down=prob_down,
            best_variant="fallback_neutral",
            best_val_accuracy=0.0,
            train_samples=0,
            val_samples=0,
            generated_at=time.time(),
        )

    def get_or_launch(self, interval: str, requested_direction: str, force_refresh: bool = False) -> LaunchResult:
        if not force_refresh:
            cached = self.get_cached(interval, requested_direction=requested_direction)
            if cached is not None:
                return cached
            stale_cached = self.get_cached_stale(interval, requested_direction=requested_direction)
            if stale_cached is not None and not self.auto_train_enabled:
                return stale_cached

        if not self.auto_train_enabled and not force_refresh:
            return self._fallback_result(interval, requested_direction, reason="auto training disabled")

        fresh = self.launch(interval, requested_direction)
        with self._cache_lock:
            self._cache[interval] = self._with_requested_direction(fresh, fresh.requested_direction)
        return fresh

    def launch(self, interval: str, requested_direction: str) -> LaunchResult:
        requested_direction = requested_direction.lower()
        if interval not in {"5m", "15m"}:
            raise ValueError(f"Unsupported interval: {interval}")
        if requested_direction not in {"up", "down"}:
            raise ValueError(f"Unsupported direction: {requested_direction}")

        best_pipeline: Optional[TrainingPipeline] = None
        best_result: Optional[dict[str, Any]] = None

        for variant in TRAINING_VARIANTS:
            try:
                pipeline, result = self._train_variant(interval, variant)
            except Exception as exc:
                logger.warning("BTC launch variant %s failed for %s: %s", variant["name"], interval, exc)
                continue
            if best_result is None or float(result["val_accuracy"]) > float(best_result["val_accuracy"]):
                best_pipeline = pipeline
                best_result = result

        if best_pipeline is None or best_result is None:
            raise RuntimeError(f"No successful BTC training variant for {interval}")

        ticker_key = f"BTC_{interval}"
        live_features = best_pipeline.latest_features_as_vector(ticker_key, max_history=50)
        if live_features is None:
            raise RuntimeError(f"No live feature vector available for {ticker_key}")
        prediction = best_pipeline.predict(ticker_key, live_features)
        if prediction is None:
            raise RuntimeError(f"No prediction available for {ticker_key}")

        prob_up = float(prediction["prob_up"])
        prob_down = float(prediction["prob_down"])
        strongest_direction = "up" if prob_up >= prob_down else "down"
        strongest_probability = max(prob_up, prob_down)

        return LaunchResult(
            interval=interval,
            requested_direction=requested_direction,
            strongest_direction=strongest_direction,
            strongest_probability=strongest_probability,
            prob_up=prob_up,
            prob_down=prob_down,
            best_variant=str(best_result["variant_name"]),
            best_val_accuracy=float(best_result["val_accuracy"]),
            train_samples=int(best_result["train_samples"]),
            val_samples=int(best_result["val_samples"]),
            generated_at=time.time(),
        )
