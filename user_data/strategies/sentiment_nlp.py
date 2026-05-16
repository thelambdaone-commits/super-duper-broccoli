import logging
import re
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
    def __init__(self, use_deberta: bool = False) -> None:
        self._keyword_scores = SENTIMENT_KEYWORDS
        self._use_deberta = use_deberta
        self._deberta_pipeline: Optional[object] = None
        if use_deberta:
            self._init_deberta()

    def _init_deberta(self) -> None:
        try:
            from transformers import pipeline
            self._deberta_pipeline = pipeline(
                "text-classification",
                model="microsoft/deberta-v3-base",
                top_k=None,
            )
            logger.info("DeBERTa pipeline loaded")
        except Exception as e:
            logger.warning(f"DeBERTa load failed (fallback to keyword): {e}")
            self._use_deberta = False

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

    def analyze_deberta(self, text: str) -> dict[str, float]:
        if self._deberta_pipeline is None:
            return self.analyze_keyword(text)
        try:
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
                }
        except Exception as e:
            logger.warning(f"DeBERTa inference failed: {e}")
        return self.analyze_keyword(text)

    def analyze(self, text: str) -> dict[str, float]:
        if self._use_deberta:
            return self.analyze_deberta(text)
        return self.analyze_keyword(text)

    def analyze_batch(self, texts: list[str]) -> list[dict[str, float]]:
        return [self.analyze(t) for t in texts]

    def to_feature_vector(self, result: dict[str, float]) -> np.ndarray:
        return np.array([
            result.get("score", 0.0),
            result.get("magnitude", 0.0),
            result.get("confidence", 0.0),
        ], dtype=np.float32)
