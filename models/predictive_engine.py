import logging
import os
import time
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from utils.exceptions import QuantFatal

logger = logging.getLogger("PredictiveEngine")

DEFAULT_MODEL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "user_data", "models"
)


class PolymarketPredictiveEngine:
    """
    Moteur Prédictif Central de niveau institutionnel.
    Exécute le pipeline, calcule le consensus de l'essaim ML, applique la 
    calibration isotonique et le time-decay lissé pour extraire l'edge.
    """

    DEFAULT_MIN_EDGE = 0.07
    TIME_DECAY_FLOOR = 0.15
    DEFAULT_MAX_BINANCE_STALENESS_SECONDS = 3.0

    def __init__(
        self,
        models_ensemble: Optional[Dict[str, Any]] = None,
        calibrator: Optional[Any] = None,
        feature_pipeline: Optional[Any] = None,
        feature_store: Optional[Any] = None,
        min_edge_threshold: float = DEFAULT_MIN_EDGE,
        allow_mock_predictions: Optional[bool] = None,
    ) -> None:
        self.models = models_ensemble or {}
        self.calibrator = calibrator
        self.pipeline = feature_pipeline
        self.feature_store = feature_store
        self.min_edge = min_edge_threshold
        self.allow_mock_predictions = (
            os.getenv("ALLOW_SIMULATED_PREDICTIVE_GATE", "false").lower() == "true"
            if allow_mock_predictions is None
            else allow_mock_predictions
        )
        self._inference_count = 0
        self._hybrid_model: Optional[Any] = None

    def _calculer_time_decay(
        self, p_calibrated: float, timestamp_resolution: float
    ) -> float:
        """
        Calcule le time-decay exponentiel avec une borne de sécurité 
        pour préserver l'agressivité microstructurelle en fin de marché.
        """
        now = time.time() if timestamp_resolution > 1_000_000_000 else time.monotonic()
        temps_restant = float(timestamp_resolution) - now

        if temps_restant <= 0:
            return 0.5

        decay_factor = 1.0 - np.exp(-temps_restant / 3600.0)

        decay_factor_scellé = max(self.TIME_DECAY_FLOOR, decay_factor)

        return 0.5 + (p_calibrated - 0.5) * decay_factor_scellé

    def _get_mock_prediction(self) -> float:
        """Génère une prédiction simulée pour test."""
        return np.random.uniform(0.55, 0.75)

    @staticmethod
    def _max_binance_staleness_seconds() -> float:
        raw_value = os.getenv(
            "MAX_BINANCE_STALENESS_SECONDS",
            str(PolymarketPredictiveEngine.DEFAULT_MAX_BINANCE_STALENESS_SECONDS),
        )
        try:
            return max(0.0, float(raw_value))
        except (TypeError, ValueError):
            logger.warning(
                "Invalid MAX_BINANCE_STALENESS_SECONDS=%r; falling back to %.1f",
                raw_value,
                PolymarketPredictiveEngine.DEFAULT_MAX_BINANCE_STALENESS_SECONDS,
            )
            return PolymarketPredictiveEngine.DEFAULT_MAX_BINANCE_STALENESS_SECONDS

    def _latest_binance_snapshot(
        self,
        ticker: str,
        max_staleness_seconds: Optional[float] = None,
    ) -> dict[str, Any]:
        if self.feature_store is None:
            raise QuantFatal("FeatureStore unavailable for live Binance feature injection")

        symbol = str(ticker or "").upper()
        if not symbol.endswith("USDT"):
            symbol = f"{symbol}USDT"

        try:
            events = self.feature_store.get_web_events(event_type="book_ticker", limit=200)
        except Exception as exc:
            raise QuantFatal(f"Unable to read Binance web events: {exc}") from exc

        latest: dict[str, Any] | None = None
        latest_ts = float("-inf")
        for event in events:
            if str(event.get("source", "")).strip() != "binance_ws":
                continue
            if str(event.get("market_slug", "")).strip().upper() != symbol:
                continue
            raw = event.get("raw") or {}
            if not isinstance(raw, dict):
                continue
            event_ts = float(event.get("timestamp") or 0.0)
            if event_ts >= latest_ts:
                latest_ts = event_ts
                latest = {
                    "timestamp": event_ts,
                    "binance_mid_price": float(raw.get("mid_price", raw.get("mid", 0.0)) or 0.0),
                    "binance_spread_bps": float(raw.get("spread_bps", raw.get("spread", 0.0)) or 0.0),
                    "binance_order_imbalance": float(raw.get("order_imbalance", 0.5) or 0.5),
                    "binance_queue_velocity": float(raw.get("queue_velocity", 0.0) or 0.0),
                    "binance_bid_volume": float(raw.get("bid_volume", raw.get("bid_depth", 0.0)) or 0.0),
                    "binance_ask_volume": float(raw.get("ask_volume", raw.get("ask_depth", 0.0)) or 0.0),
                }

        if latest is None:
            raise QuantFatal(f"No Binance snapshot available for {symbol}")

        now = time.time()
        max_staleness_seconds = (
            self._max_binance_staleness_seconds()
            if max_staleness_seconds is None
            else float(max_staleness_seconds)
        )
        drift = now - float(latest["timestamp"])
        if drift < 0:
            raise QuantFatal(
                f"Lookahead bias detected for {symbol}: snapshot timestamp is {abs(drift):.3f}s in the future"
            )
        if drift > max_staleness_seconds:
            raise QuantFatal(
                f"Binance snapshot for {symbol} is stale by {drift:.3f}s; inference blocked"
            )
        return latest

    def get_live_prediction(
        self,
        ticker: str,
        polymarket_frame: Dict[str, Any],
        clob_price_yes: float,
        timestamp_resolution: float,
        max_staleness_seconds: Optional[float] = None,
    ) -> Dict[str, Any]:
        binance_snapshot = self._latest_binance_snapshot(
            ticker=ticker,
            max_staleness_seconds=max_staleness_seconds,
        )
        live_features = {**polymarket_frame, **binance_snapshot}
        df_live = pd.DataFrame(self._normalize_market_feature_rows(live_features))
        if df_live.empty:
            raise QuantFatal("Live feature matrix is empty after Binance injection")
        return self.predict_winning_bet(
            df_market_ticks=df_live,
            clob_price_yes=clob_price_yes,
            timestamp_resolution=timestamp_resolution,
        )

    @staticmethod
    def _extract_positive_probability(prediction: Any) -> float:
        arr = np.asarray(prediction, dtype=np.float64)
        if arr.ndim == 0:
            return float(arr)
        if arr.ndim == 1:
            if arr.shape[0] >= 2:
                return float(arr[1])
            return float(arr[0])
        if arr.shape[1] >= 2:
            return float(arr[0, 1])
        return float(arr[0, 0])

    def _predict_model_probability(self, model: Any, X_live: np.ndarray) -> float:
        if hasattr(model, "predict_proba"):
            return self._extract_positive_probability(model.predict_proba(X_live))
        if hasattr(model, "predict"):
            return self._extract_positive_probability(model.predict(X_live))
        if callable(model):
            return self._extract_positive_probability(model(X_live))
        raise TypeError(f"Unsupported model interface: {type(model).__name__}")

    def _apply_calibrator(self, raw_score: float) -> float:
        if not self.calibrator:
            return raw_score
        scores = np.array([[1.0 - raw_score, raw_score]], dtype=np.float64)
        if hasattr(self.calibrator, "predict_proba"):
            return self._extract_positive_probability(self.calibrator.predict_proba(scores))
        if callable(self.calibrator):
            return self._extract_positive_probability(self.calibrator(scores))
        if hasattr(self.calibrator, "calibrate"):
            logger.warning("Calibrator exposes calibrate() only; skipping inference-time recalibration")
        return raw_score

    def predict_winning_bet(
        self,
        df_market_ticks: pd.DataFrame,
        clob_price_yes: float,
        timestamp_resolution: float,
    ) -> Dict[str, Any]:
        """
        Exécute la matrice d'inférence en 6 étapes déterministes.
        """
        start_time = time.perf_counter()
        self._inference_count += 1

        try:
            if self._hybrid_model is not None:
                X_live = self.pipeline.transform(df_market_ticks) if self.pipeline else df_market_ticks.values
                raw_score = self._predict_model_probability(self._hybrid_model, X_live)
                logger.info("🔮 Using HybridQuantModel for prediction")
            elif self.models and self.pipeline:
                X_live = self.pipeline.transform(df_market_ticks)
                probabilities = [
                    self._predict_model_probability(model, X_live)
                    for model in self.models.values()
                ]
                if not probabilities:
                    raise ValueError("No ensemble models available")
                raw_score = float(np.mean(np.clip(probabilities, 0.0, 1.0)))
            else:
                if not self.allow_mock_predictions:
                    return {
                        "pari_approuve": False,
                        "probability_win": 0.5,
                        "absolute_edge": 0.0,
                        "clob_price": clob_price_yes,
                        "latency_ms": (time.perf_counter() - start_time) * 1000,
                        "inference_count": self._inference_count,
                        "conclusion": "REJECT_NO_MODEL",
                    }
                raw_score = self._get_mock_prediction()
                logger.warning("🔮 Using explicitly enabled simulated prediction")

            p_calibrated = self._apply_calibrator(float(np.clip(raw_score, 0.0, 1.0)))

            p_final = self._calculer_time_decay(p_calibrated, timestamp_resolution)

            absolute_edge = p_final - clob_price_yes

            pari_approuve = absolute_edge >= self.min_edge

            conclusion = (
                "EXECUTE_TRADE" if pari_approuve else "REJECT_NO_EDGE"
            )

            latency_ms = (time.perf_counter() - start_time) * 1000

            logger.info(
                f"🔮 [PREDICTION] P_final={p_final:.1%} | Price={clob_price_yes:.2f} | "
                f"Edge={absolute_edge:+.1%} | Decision={conclusion} | Latency={latency_ms:.2f}ms"
            )

            return {
                "pari_approuve": pari_approuve,
                "probability_win": float(p_final),
                "absolute_edge": float(absolute_edge),
                "clob_price": clob_price_yes,
                "latency_ms": latency_ms,
                "inference_count": self._inference_count,
                "conclusion": conclusion,
            }

        except Exception as e:
            logger.error(f"❌ Prediction engine error: {e}")
            return {
                "pari_approuve": False,
                "probability_win": 0.5,
                "absolute_edge": 0.0,
                "clob_price": clob_price_yes,
                "latency_ms": 0.0,
                "inference_count": self._inference_count,
                "conclusion": "REJECT_ERROR",
                "error": str(e),
            }

    def calculate_kelly_size(
        self,
        probability_win: float,
        clob_price: float,
        max_kelly: float = 0.25,
    ) -> float:
        """
        Calcule la taille de position via Kelly Criterion.
        """
        probability_win = float(np.clip(probability_win, 0.0, 1.0))
        if probability_win <= 0.5 or clob_price <= 0.0 or clob_price >= 1.0:
            return 0.0

        payout = (1.0 - clob_price) / clob_price
        if payout <= 0:
            return 0.0

        q = 1.0 - probability_win
        kelly = (probability_win * payout - q) / payout

        kelly = max(0.0, min(kelly, max_kelly))

        return kelly

    def get_stats(self) -> Dict[str, Any]:
        return {
            "inference_count": self._inference_count,
            "min_edge_threshold": self.min_edge,
            "time_decay_floor": self.TIME_DECAY_FLOOR,
            "allow_mock_predictions": self.allow_mock_predictions,
        }

    def load_models(
        self,
        model_dir: str = DEFAULT_MODEL_DIR,
        hybrid_model_path: Optional[str] = None,
        calibrator_path: Optional[str] = None,
    ) -> "PolymarketPredictiveEngine":
        """
        Charge les modèles réel HybridQuantModel et ProbabilityCalibrator depuis le disk.
        """
        os.makedirs(model_dir, exist_ok=True)

        if hybrid_model_path is None:
            hybrid_model_path = os.path.join(model_dir, "hybrid_model.pkl")

        if calibrator_path is None:
            calibrator_path = os.path.join(model_dir, "probability_calibrator.pkl")

        if os.path.exists(hybrid_model_path):
            try:
                from user_data.freqaimodels.HybridQuantModel import HybridQuantModel
                self._hybrid_model = HybridQuantModel().load(hybrid_model_path)
                logger.info(f"✅ HybridQuantModel loaded from {hybrid_model_path}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to load HybridQuantModel: {e}")

        if os.path.exists(calibrator_path):
            try:
                from user_data.strategies.probability_calibrator import ProbabilityCalibrator
                self.calibrator = ProbabilityCalibrator().load(calibrator_path)
                logger.info(f"✅ ProbabilityCalibrator loaded from {calibrator_path}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to load ProbabilityCalibrator: {e}")

        return self


def create_predictive_engine(
    min_edge_threshold: float = 0.07,
    load_models: bool = True,
    model_dir: str = DEFAULT_MODEL_DIR,
) -> PolymarketPredictiveEngine:
    """
    Factory function pour créer le PredictiveEngine avec config par défaut.
    """
    engine = PolymarketPredictiveEngine(
        min_edge_threshold=min_edge_threshold
    )

    if load_models:
        engine.load_models(model_dir=model_dir)

    return engine
