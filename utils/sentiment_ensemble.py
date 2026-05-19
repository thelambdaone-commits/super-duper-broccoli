import logging
import os
from typing import Any, Optional

logger = logging.getLogger("SentimentEnsemble")


class SentimentEnsemble:
    def __init__(
        self,
        use_vader: bool = True,
        use_finbert: bool = True,
        use_textblob: bool = False,
        finbert_model: str = "ProsusAI/finbert",
    ):
        self.use_vader = use_vader
        self.use_finbert = use_finbert
        self.use_textblob = use_textblob
        self.finbert_model = finbert_model
        self._vader: Any = None
        self._finbert: Any = None
        self._textblob: Any = None
        self._init_models()

    def _init_models(self) -> None:
        if self.use_vader:
            try:
                from nltk.sentiment import SentimentIntensityAnalyzer
                self._vader = SentimentIntensityAnalyzer()
                logger.info("VADER loaded")
            except Exception as e:
                logger.warning("VADER init failed: %s", e)
                self.use_vader = False
        if self.use_finbert:
            if not self._allow_remote_models() and not self._is_local_model_path(self.finbert_model):
                logger.info("FinBERT disabled in offline mode; using non-FinBERT signals only")
                self.use_finbert = False
                self._finbert = None
                return
            try:
                from transformers import pipeline
                self._finbert = pipeline(
                    "sentiment-analysis",
                    model=self.finbert_model,
                    tokenizer=self.finbert_model,
                )
                logger.info("FinBERT loaded: %s", self.finbert_model)
            except Exception as e:
                logger.warning("FinBERT init failed: %s", e)
                self.use_finbert = False
        if self.use_textblob:
            try:
                from textblob import TextBlob
                self._textblob = TextBlob
                logger.info("TextBlob loaded")
            except Exception as e:
                logger.warning("TextBlob init failed: %s", e)
                self.use_textblob = False

    def analyze(self, text: str) -> dict:
        scores = {}
        weights = {}

        if self._vader:
            v = self._vader.polarity_scores(text)
            scores["vader"] = v["compound"]
            weights["vader"] = 0.3

        if self._finbert:
            try:
                r = self._finbert(text[:512])[0]
                label, conf = r["label"], r["score"]
                score = conf if label.upper() == "POSITIVE" else -conf if label.upper() == "NEGATIVE" else 0.0
                scores[f"finbert_{self.finbert_model.split('/')[-1]}"] = score
                weights[f"finbert_{self.finbert_model.split('/')[-1]}"] = 0.5
            except Exception as e:
                logger.warning("FinBERT inference error: %s", e)

        if self._textblob:
            tb = self._textblob(text)
            scores["textblob"] = tb.sentiment.polarity
            weights["textblob"] = 0.2

        if not scores:
            return {"ensemble_score": 0.0, "detailed": {}, "confidence": 0.0}

        total_weight = sum(weights.values())
        if total_weight > 0:
            ensemble = sum(scores[k] * weights[k] for k in scores) / total_weight
        else:
            ensemble = 0.0

        conf = max(w for k, w in weights.items() if k in scores) if scores else 0.0
        return {
            "ensemble_score": round(ensemble, 4),
            "detailed": {k: round(v, 4) for k, v in scores.items()},
            "confidence": round(conf, 4),
        }

    def analyze_batch(self, texts: list[str]) -> list[dict]:
        return [self.analyze(t) for t in texts]

    def get_status(self) -> dict:
        return {
            "vader_loaded": self._vader is not None,
            "finbert_loaded": self._finbert is not None,
            "textblob_loaded": self._textblob is not None,
            "finbert_model": self.finbert_model,
        }

    @staticmethod
    def _allow_remote_models() -> bool:
        return os.getenv("HF_ALLOW_REMOTE_MODELS", "").strip().lower() in {"1", "true", "yes"}

    @staticmethod
    def _is_local_model_path(model_name: str) -> bool:
        return os.path.isdir(model_name) or os.path.isfile(model_name)
