import logging
import os
import time
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from utils.exceptions import QuantFatal
from utils.config_loader import get_health_config

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

        # SECURITY: Mode guard to prevent random mock trades in real-capital modes
        if self.allow_mock_predictions:
            mode = os.getenv("EXECUTION_MODE", "PAPER").upper()
            is_real = os.getenv("REAL", "false").lower() == "true"
            if is_real or mode in ("PROD", "SHADOW"):
                logger.warning("🚨 [SECURITY] Simulated predictive gate FORCE-DISABLED for live mode: %s", mode)
                self.allow_mock_predictions = False

        self._inference_count = 0
        self._hybrid_model: Optional[Any] = None
        self._models_cache: Dict[str, Any] = {}
        self._calibrators_cache: Dict[str, Any] = {}
        self._timesfm: Optional[Any] = None
        
        try:
            from .timesfm_adapter import TimesFMAdapter
            self._timesfm = TimesFMAdapter()
        except Exception as e:
            logger.debug(f"TimesFM adapter unavailable: {e}")

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
            str(get_health_config("binance_staleness_seconds", PolymarketPredictiveEngine.DEFAULT_MAX_BINANCE_STALENESS_SECONDS)),
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
            # Check for any depth or book_ticker events from Binance
            events = self.feature_store.get_web_events(limit=500)
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
        try:
            binance_snapshot = self._latest_binance_snapshot(
                ticker=ticker,
                max_staleness_seconds=max_staleness_seconds,
            )
            live_features = {**polymarket_frame, **binance_snapshot}
        except Exception as e:
            logger.debug(f"Binance benchmark unavailable for {ticker}: {e}. Using Polymarket features only.")
            live_features = polymarket_frame

        df_live = pd.DataFrame(self._normalize_market_feature_rows(live_features))
        if df_live.empty:
            raise QuantFatal("Live feature matrix is empty after Binance injection")
        return self.predict_winning_bet(
            df_market_ticks=df_live,
            clob_price_yes=clob_price_yes,
            timestamp_resolution=timestamp_resolution,
            ticker=ticker,
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

    def _apply_calibrator(self, raw_score: float, ticker: Optional[str] = None) -> float:
        calibrator = self._get_calibrator_for_ticker(ticker or "")
        if not calibrator:
            return raw_score
        scores = np.array([[1.0 - raw_score, raw_score]], dtype=np.float64)
        if hasattr(calibrator, "predict_proba"):
            return self._extract_positive_probability(calibrator.predict_proba(scores))
        if callable(calibrator):
            return self._extract_positive_probability(calibrator(scores))
        if hasattr(calibrator, "predict"):
             # IsotonicRegression.predict usually takes 1D array
             return self._extract_positive_probability(calibrator.predict(np.array([raw_score])))
        return raw_score

    def _normalize_market_feature_rows(self, features: Any) -> list[dict[str, Any]]:
        if features is None:
            return []
        if isinstance(features, list):
            if not features:
                return []
            if all(isinstance(row, dict) for row in features):
                return features
            return [{"value": row} for row in features]
        if isinstance(features, dict):
            if any(isinstance(value, list) for value in features.values()):
                keys = list(features.keys())
                max_len = max(
                    (len(value) for value in features.values() if isinstance(value, list)),
                    default=0,
                )
                rows: list[dict[str, Any]] = []
                for idx in range(max_len or 1):
                    row: dict[str, Any] = {}
                    for key in keys:
                        value = features[key]
                        if isinstance(value, list):
                            row[key] = value[idx] if idx < len(value) else value[-1] if value else None
                        else:
                            row[key] = value
                    rows.append(row)
                return rows
            return [features]
        return [{"value": features}]

    def predict_winning_bet(
        self,
        df_market_ticks: pd.DataFrame,
        clob_price_yes: float,
        timestamp_resolution: float,
        ticker: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Exécute la matrice d'inférence en 6 étapes déterministes.
        """
        start_time = time.perf_counter()
        self._inference_count += 1

        try:
            ensemble_scores = []
            
            # Use ticker-specific model if available
            target_model = self._get_model_for_ticker(ticker or "")
            
            if target_model is not None:
                X_live = self.pipeline.transform(df_market_ticks) if self.pipeline else df_market_ticks.values
                ensemble_scores.append(self._predict_model_probability(target_model, X_live))
                logger.info(f"🔮 Using {'specific' if ticker else 'global'} HybridQuantModel for prediction")
            elif self.models and self.pipeline:
                X_live = self.pipeline.transform(df_market_ticks)
                for model in self.models.values():
                    ensemble_scores.append(self._predict_model_probability(model, X_live))
            
            # TimesFM Integration
            if self._timesfm and not df_market_ticks.empty:
                try:
                    # Forecast based on the last 20 mid-prices
                    history = df_market_ticks["mid_price"] if "mid_price" in df_market_ticks.columns else pd.Series()
                    if not history.empty:
                        forecast = self._timesfm.forecast(history, horizon=5)
                        # Derive a 'probability' from the forecast (e.g. is final value higher than current?)
                        tfm_score = 0.5 + (0.1 if forecast[-1] > history.iloc[-1] else -0.1)
                        ensemble_scores.append(tfm_score)
                        logger.info(f"🔮 TimesFM ensemble contribution: {tfm_score:.2f}")
                except Exception as e:
                    logger.debug(f"TimesFM inference failed: {e}")

            if ensemble_scores:
                raw_score = float(np.mean(np.clip(ensemble_scores, 0.0, 1.0)))
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

            p_calibrated = self._apply_calibrator(float(np.clip(raw_score, 0.0, 1.0)), ticker=ticker)

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

    def _get_model_for_ticker(self, ticker: str) -> Optional[Any]:
        """Resolves the best matching model for a given ticker."""
        if not ticker:
            return self._hybrid_model
        
        # 0. Normalize to canonical asset (e.g. "will-bitcoin-hit-100k" -> "BTC")
        from utils.ticker_utils import normalize_to_asset
        asset_canonical = normalize_to_asset(ticker)
        
        # Exact match (e.g. "BTC_15m")
        if ticker in self._models_cache:
            return self._models_cache[ticker]
            
        # Canonical match (e.g. "BTC")
        if asset_canonical in self._models_cache:
            return self._models_cache[asset_canonical]
        
        # Asset-only match (e.g. ticker="BTC", model="BTC_hybrid.pkl")
        asset_base = ticker.split("_")[0].upper()
        if asset_base in self._models_cache:
            return self._models_cache[asset_base]
            
        # Fallback to any model for this asset, preferring 15m standard
        preferred = f"{asset_canonical}_15M"
        if preferred in self._models_cache:
            return self._models_cache[preferred]
            
        # Also try asset_base fallback
        preferred_base = f"{asset_base}_15M"
        if preferred_base in self._models_cache:
            return self._models_cache[preferred_base]

        for key in self._models_cache:
            if key.startswith(f"{asset_canonical}_") or key.startswith(f"{asset_base}_"):
                return self._models_cache[key]
                
        return self._hybrid_model

    def _get_calibrator_for_ticker(self, ticker: str) -> Optional[Any]:
        """Resolves the best matching calibrator for a given ticker."""
        if not ticker:
            return self.calibrator
        
        from utils.ticker_utils import normalize_to_asset
        asset_canonical = normalize_to_asset(ticker)
        
        asset_base = ticker.split("_")[0].upper()
        if ticker in self._calibrators_cache:
            return self._calibrators_cache[ticker]
        if asset_canonical in self._calibrators_cache:
            return self._calibrators_cache[asset_canonical]
        if asset_base in self._calibrators_cache:
            return self._calibrators_cache[asset_base]
            
        preferred = f"{asset_canonical}_15M"
        if preferred in self._calibrators_cache:
            return self._calibrators_cache[preferred]

        for key in self._calibrators_cache:
            if key.startswith(f"{asset_canonical}_") or key.startswith(f"{asset_base}_"):
                return self._calibrators_cache[key]
                
        return self.calibrator

    def load_models(
        self,
        model_dir: str = DEFAULT_MODEL_DIR,
        hybrid_model_path: Optional[str] = None,
        calibrator_path: Optional[str] = None,
    ) -> "PolymarketPredictiveEngine":
        """
        Charge les modèles réel HybridQuantModel et ProbabilityCalibrator depuis le disk.
        Supporte le chargement massif par asset ({ticker}_hybrid.pkl).
        """
        os.makedirs(model_dir, exist_ok=True)
        
        # 1. Mass discovery
        try:
            from user_data.freqaimodels.HybridQuantModel import HybridQuantModel
            from strategies.probability_calibrator import ProbabilityCalibrator
            
            for filename in os.listdir(model_dir):
                if filename.endswith("_hybrid.pkl"):
                    ticker_key = filename.replace("_hybrid.pkl", "").upper()
                    try:
                        self._models_cache[ticker_key] = HybridQuantModel().load(os.path.join(model_dir, filename))
                        logger.info(f"✅ Loaded specific model: {ticker_key}")
                    except Exception as e:
                        logger.warning(f"Failed to load specific model {filename}: {e}")
                
                elif filename.endswith("_calibrator.pkl"):
                    ticker_key = filename.replace("_calibrator.pkl", "").upper()
                    try:
                        # ProbabilityCalibrator doesn't have .load() in some versions? 
                        # Let's check strategies/probability_calibrator.py
                        with open(os.path.join(model_dir, filename), "rb") as f:
                            import pickle
                            self._calibrators_cache[ticker_key] = pickle.load(f)
                        logger.info(f"✅ Loaded specific calibrator: {ticker_key}")
                    except Exception as e:
                        logger.warning(f"Failed to load specific calibrator {filename}: {e}")
        except Exception as e:
            logger.warning(f"Model discovery failed: {e}")

        # 2. Legacy/Explicit path loading
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
                from strategies.probability_calibrator import ProbabilityCalibrator
                # Support both pickle and custom .load()
                try:
                    self.calibrator = ProbabilityCalibrator().load(calibrator_path)
                except Exception:
                    with open(calibrator_path, "rb") as f:
                        import pickle
                        self.calibrator = pickle.load(f)
                logger.info(f"✅ ProbabilityCalibrator loaded from {calibrator_path}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to load ProbabilityCalibrator: {e}")

        return self


def create_predictive_engine(
    min_edge_threshold: float = 0.07,
    load_models: bool = True,
    model_dir: str = DEFAULT_MODEL_DIR,
    feature_store: Optional[Any] = None,
) -> PolymarketPredictiveEngine:
    """
    Factory function pour créer le PredictiveEngine avec config par défaut.
    """
    engine = PolymarketPredictiveEngine(
        min_edge_threshold=min_edge_threshold,
        feature_store=feature_store
    )

    if load_models:
        engine.load_models(model_dir=model_dir)

    return engine
