import logging
import os
from typing import Optional

import numpy as np

logger = logging.getLogger("SentimentNLP")

SENTIMENT_KEYWORDS = {
    "bullish": 0.3, "bull": 0.25, "moon": 0.3, "pump": 0.25,
    "breakout": 0.2, "uptrend": 0.2, "green": 0.1, "gains": 0.15,
    "accumulation": 0.15, "support": 0.1, "oversold": 0.15,
    "buy_dip": 0.2, "hodl": 0.1, "catalyst": 0.2, "partnership": 0.2,
    "adoption": 0.15, "upgrade": 0.15, "mainnet": 0.15,
    "beat_estimates": 0.25, "positive": 0.1,
    "bearish": -0.3, "bear": -0.25, "dump": -0.3, "crash": -0.35,
    "breakdown": -0.2, "downtrend": -0.2, "red": -0.1, "losses": -0.15,
    "distribution": -0.15, "resistance": -0.1, "overbought": -0.15,
    "sell": -0.2, "fud": -0.25, "fear": -0.15, "capitulation": -0.3,
    "delist": -0.3, "hack": -0.35, "exploit": -0.3, "regulatory": -0.2,
    "negative": -0.1, "bankruptcy": -0.4, "rug": -0.4,
}


class SentimentAnalyzer:
    def __init__(self, use_deberta: bool = False, use_finbert: bool = False, finbert_model: str = "ProsusAI/finbert", hf_token: Optional[str] = None) -> None:
        self._keyword_scores = SENTIMENT_KEYWORDS
        self._use_deberta = use_deberta
        self._use_finbert = use_finbert
        self._finbert_model = finbert_model
        self._hf_token = hf_token or os.getenv("HUGGINGFACE_API_KEY", "")
        self._deberta_pipeline: Optional[object] = None
        self._finbert_pipeline: Optional[object] = None
        self._hf_client_deberta: Optional[object] = None
        self._hf_client_finbert: Optional[object] = None

        if use_deberta:
            self._init_deberta()
        if use_finbert:
            self._init_finbert()

    def _init_deberta(self) -> None:
        # Try API first
        if self._hf_token:
            try:
                from huggingface_hub import InferenceClient
                self._hf_client_deberta = InferenceClient(model="microsoft/deberta-v3-base", token=self._hf_token)
                logger.info("Using HF Inference API for DeBERTa")
                return
            except Exception as e:
                logger.warning(f"HF Inference API for DeBERTa init failed: {e}")

        # Local fallback
        if not self._allow_remote_models() and not self._is_local_model_path("microsoft/deberta-v3-base"):
            logger.info("DeBERTa disabled in offline mode; using keyword fallback")
            self._use_deberta = False
            return
        try:
            from transformers import pipeline
            self._deberta_pipeline = pipeline(
                "text-classification",
                model="microsoft/deberta-v3-base",
                top_k=None,
            )
            logger.info("DeBERTa pipeline loaded locally")
        except Exception as e:
            logger.warning(f"DeBERTa load failed (fallback to keyword): {e}")
            self._use_deberta = False

    def _init_finbert(self) -> None:
        # Try API first
        if self._hf_token:
            try:
                from huggingface_hub import InferenceClient
                self._hf_client_finbert = InferenceClient(model=self._finbert_model, token=self._hf_token)
                logger.info("Using HF Inference API for FinBERT")
                return
            except Exception as e:
                logger.warning(f"HF Inference API for FinBERT init failed: {e}")

        # Local fallback
        if not self._allow_remote_models() and not self._is_local_model_path(self._finbert_model):
            logger.info("FinBERT disabled in offline mode; using keyword fallback")
            self._use_finbert = False
            return
        try:
            from transformers import pipeline
            self._finbert_pipeline = pipeline(
                "sentiment-analysis",
                model=self._finbert_model,
                tokenizer=self._finbert_model,
            )
            logger.info("FinBERT pipeline loaded locally: %s", self._finbert_model)
        except Exception as e:
            logger.warning(f"FinBERT load failed: {e}")
            self._use_finbert = False

    def analyze_keyword(self, text: str) -> dict[str, float]:
        text_lower = text.lower()
        scores: list[float] = []
        matches: list[str] = []
        for word, score in self._keyword_scores.items():
            if word in text_lower:
                scores.append(score)
                matches.append(word)
        if not scores:
            return {"score": 0.0, "magnitude": 0.0, "confidence": 0.0, "matches": []}
        mean_score = sum(scores) / len(scores)
        magnitude = sum(abs(s) for s in scores) / len(scores)
        confidence = min(1.0, len(scores) / 5.0)
        return {
            "score": round(float(mean_score), 4),
            "magnitude": round(float(magnitude), 4),
            "confidence": round(float(confidence), 4),
            "matches": matches,
        }

    def analyze_finbert(self, text: str) -> dict[str, float]:
        if self._hf_client_finbert is None and self._finbert_pipeline is None:
            return self.analyze_keyword(text)

        try:
            # Option A: API
            if self._hf_client_finbert:
                try:
                    from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_message
                    @retry(
                        stop=stop_after_attempt(2),
                        wait=wait_exponential(multiplier=1, min=2, max=5),
                        retry=retry_if_exception_message(match=".*loading.*")
                    )
                    def query_api(t):
                        return self._hf_client_finbert.text_classification(t[:512])

                    res = query_api(text)
                    if res:
                        best = max(res, key=lambda x: x["score"])
                        label, score = best["label"].upper(), best["score"]
                        net = score if label == "POSITIVE" else -score if label == "NEGATIVE" else 0.0
                        return {
                            "score": round(float(net), 4),
                            "magnitude": round(float(abs(net)), 4),
                            "confidence": round(float(score), 4),
                            "model": self._finbert_model,
                            "label": label,
                            "source": "hf_api"
                        }
                except Exception as e:
                    logger.warning("HF API FinBERT failed: %s", e)

            # Option B: Local
            if self._finbert_pipeline:
                result = self._finbert_pipeline(text[:512])
                if isinstance(result, list) and len(result) > 0:
                    label = result[0].get("label", "NEUTRAL").upper()
                    score = result[0].get("score", 0.0)
                    net = score if label == "POSITIVE" else -score if label == "NEGATIVE" else 0.0
                    return {
                        "score": round(float(net), 4),
                        "magnitude": round(float(abs(net)), 4),
                        "confidence": round(float(score), 4),
                        "model": self._finbert_model,
                        "label": label,
                        "source": "local"
                    }
        except Exception as e:
            logger.warning("FinBERT inference failed: %s", e)
        return self.analyze_keyword(text)

    def analyze_deberta(self, text: str) -> dict[str, float]:
        if self._hf_client_deberta is None and self._deberta_pipeline is None:
            return self.analyze_keyword(text)

        try:
            # Option A: API
            if self._hf_client_deberta:
                try:
                    from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_message
                    @retry(
                        stop=stop_after_attempt(2),
                        wait=wait_exponential(multiplier=1, min=2, max=5),
                        retry=retry_if_exception_message(match=".*loading.*")
                    )
                    def query_api(t):
                        return self._hf_client_deberta.text_classification(t[:512])

                    res = query_api(text)
                    if res:
                        label_map = {r["label"]: r["score"] for r in res}
                        pos = label_map.get("POSITIVE", 0.0)
                        neg = label_map.get("NEGATIVE", 0.0)
                        neu = label_map.get("NEUTRAL", 0.0)
                        net = pos - neg
                        confidence = max(pos, neg, neu)
                        return {
                            "score": round(float(net), 4),
                            "magnitude": round(float(pos + neg), 4),
                            "confidence": round(float(confidence), 4),
                            "deberta_raw": {k: round(float(v), 4) for k, v in label_map.items()},
                            "source": "hf_api"
                        }
                except Exception as e:
                    logger.warning("HF API DeBERTa failed: %s", e)

            # Option B: Local
            if self._deberta_pipeline:
                result = self._deberta_pipeline(text[:512])
                if isinstance(result, list) and len(result) > 0:
                    label_map = {r["label"]: r["score"] for r in result[0]}
                    pos = label_map.get("POSITIVE", 0.0)
                    neg = label_map.get("NEGATIVE", 0.0)
                    neu = label_map.get("NEUTRAL", 0.0)
                    net = pos - neg
                    confidence = max(pos, neg, neu)
                    return {
                        "score": round(float(net), 4),
                        "magnitude": round(float(pos + neg), 4),
                        "confidence": round(float(confidence), 4),
                        "deberta_raw": {k: round(float(v), 4) for k, v in label_map.items()},
                        "source": "local"
                    }
        except Exception as e:
            logger.warning(f"DeBERTa inference failed: {e}")
        return self.analyze_keyword(text)

    def analyze(self, text: str) -> dict[str, float]:
        if self._use_finbert:
            return self.analyze_finbert(text)
        if self._use_deberta:
            return self.analyze_deberta(text)
        return self.analyze_keyword(text)

    def analyze_batch(self, texts: list[str]) -> list[dict[str, float]]:
        return [self.analyze(t) for t in texts]

    @staticmethod
    def _allow_remote_models() -> bool:
        return os.getenv("HF_ALLOW_REMOTE_MODELS", "").strip().lower() in {"1", "true", "yes"}

    @staticmethod
    def _is_local_model_path(model_name: str) -> bool:
        return os.path.isdir(model_name) or os.path.isfile(model_name)

    def to_feature_vector(self, result: dict[str, float]) -> np.ndarray:
        return np.array([
            result.get("score", 0.0),
            result.get("magnitude", 0.0),
            result.get("confidence", 0.0),
        ], dtype=np.float32)
