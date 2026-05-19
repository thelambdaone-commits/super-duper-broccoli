import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from user_data.strategies.sentiment_nlp import SENTIMENT_KEYWORDS

logger = logging.getLogger("EarningsSentimentPipeline")


@dataclass
class EarningsResult:
    ticker: str
    quarter: str
    year: int
    sentiment_score: float
    confidence: float
    key_themes: list[str] = field(default_factory=list)
    qualitative_assessment: str = ""
    stock_performance_1w: Optional[float] = None
    stock_performance_1m: Optional[float] = None
    stock_performance_3m: Optional[float] = None
    alpha_vs_sp500: Optional[float] = None
    error: Optional[str] = None


class EarningsSentimentPipeline:
    def __init__(
        self,
        gemini_api_key: Optional[str] = None,
        fmp_api_key: Optional[str] = None,
        use_huggingface: bool = True,
        hf_model: str = "ProsusAI/finbert",
        db_path: Optional[str] = None,
    ):
        self.gemini_api_key = gemini_api_key or os.getenv("GEMINI_API_KEY", "")
        self.fmp_api_key = fmp_api_key or os.getenv("FMP_API_KEY", "")
        self.use_huggingface = use_huggingface
        self.hf_model = hf_model
        self.db_path = db_path or os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "user_data", "data", "earnings_sentiment.db"
        )
        self._hf_pipeline: Any = None
        self._analyzer: Any = None
        self._earnings_analyzer_available = False
        self._init_earnings_analyzer()

    def _init_earnings_analyzer(self) -> None:
        try:
            from earnings_analyzer.api import quick_sentiment_analysis
            self._quick_sentiment = quick_sentiment_analysis
            self._earnings_analyzer_available = True
            logger.info("earnings-analyzer package available")
        except ImportError:
            self._earnings_analyzer_available = False
            logger.info("earnings-analyzer not installed; use pip install earnings-analyzer")

    def _get_hf_sentiment(self, text: str) -> dict:
        if not self.use_huggingface:
            return self._keyword_sentiment(text)
        if self._hf_pipeline is None:
            if not self._allow_remote_models() and not self._is_local_model_path(self.hf_model):
                logger.info("HF model %s disabled in offline mode; using keyword fallback", self.hf_model)
                return self._keyword_sentiment(text)
            try:
                from transformers import pipeline
                self._hf_pipeline = pipeline(
                    "sentiment-analysis",
                    model=self.hf_model,
                    tokenizer=self.hf_model,
                )
                logger.info("Loaded HF model: %s", self.hf_model)
            except Exception as e:
                logger.warning("Failed to load HF model %s: %s", self.hf_model, e)
                return self._keyword_sentiment(text)
        try:
            result = self._hf_pipeline(text[:512])[0]
            label = result["label"].upper()
            score = result["score"]
            if label == "POSITIVE":
                return {"score": score, "label": "POSITIVE", "confidence": score}
            elif label == "NEGATIVE":
                return {"score": -score, "label": "NEGATIVE", "confidence": score}
            return {"score": 0.0, "label": "NEUTRAL", "confidence": score}
        except Exception as e:
            logger.warning("HF sentiment error: %s", e)
            return self._keyword_sentiment(text)

    def analyze_earnings_call(
        self,
        ticker: str,
        quarter: Optional[str] = None,
        year: Optional[int] = None,
    ) -> EarningsResult:
        if self._earnings_analyzer_available and self.gemini_api_key:
            try:
                result = self._quick_sentiment(
                    ticker=ticker,
                    gemini_api_key=self.gemini_api_key,
                    quarter=quarter,
                    year=year,
                )
                return EarningsResult(
                    ticker=ticker,
                    quarter=result.get("quarter", quarter or ""),
                    year=result.get("year", year or 0),
                    sentiment_score=result.get("overall_sentiment_score", 5.0) / 10.0,
                    confidence=result.get("confidence_level", 0.5),
                    key_themes=result.get("key_themes", []),
                    qualitative_assessment=result.get("qualitative_assessment", ""),
                    stock_performance_1w=result.get("stock_performance_1w"),
                    stock_performance_1m=result.get("stock_performance_1m"),
                    stock_performance_3m=result.get("stock_performance_3m"),
                )
            except Exception as e:
                logger.warning("earnings-analyzer failed for %s: %s", ticker, e)
        return EarningsResult(
            ticker=ticker, quarter=quarter or "", year=year or 0,
            error="earnings-analyzer not configured",
        )

    def analyze_text_sentiment(self, text: str) -> dict:
        hf_result = self._get_hf_sentiment(text)
        return {
            "score": hf_result["score"],
            "label": hf_result["label"],
            "confidence": hf_result["confidence"],
            "model": self.hf_model,
        }

    def batch_analyze_texts(self, texts: list[str]) -> list[dict]:
        return [self.analyze_text_sentiment(t) for t in texts]

    @staticmethod
    def _allow_remote_models() -> bool:
        return os.getenv("HF_ALLOW_REMOTE_MODELS", "").strip().lower() in {"1", "true", "yes"}

    @staticmethod
    def _is_local_model_path(model_name: str) -> bool:
        return os.path.isdir(model_name) or os.path.isfile(model_name)

    @staticmethod
    def _keyword_sentiment(text: str) -> dict:
        text_lower = text.lower()
        matches = [word for word in SENTIMENT_KEYWORDS if word in text_lower]
        if not matches:
            return {"score": 0.0, "label": "NEUTRAL", "confidence": 0.0}

        scores = [SENTIMENT_KEYWORDS[word] for word in matches]
        score = sum(scores) / len(scores)
        if score > 0:
            label = "POSITIVE"
        elif score < 0:
            label = "NEGATIVE"
        else:
            label = "NEUTRAL"
        confidence = min(1.0, len(matches) / 5.0)
        return {
            "score": round(float(score), 4),
            "label": label,
            "confidence": round(float(confidence), 4),
        }

    def get_status(self) -> dict:
        return {
            "hf_model": self.hf_model,
            "use_huggingface": self.use_huggingface,
            "earnings_analyzer_available": self._earnings_analyzer_available,
            "gemini_configured": bool(self.gemini_api_key),
            "fmp_configured": bool(self.fmp_api_key),
        }
