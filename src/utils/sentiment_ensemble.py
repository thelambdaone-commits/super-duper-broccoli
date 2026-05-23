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
        hf_token: Optional[str] = None,
    ):
        self.use_vader = use_vader
        self.use_finbert = use_finbert
        self.use_textblob = use_textblob
        self.finbert_model = finbert_model
        self.hf_token = hf_token or os.getenv("HUGGINGFACE_API_KEY", "")
        self._vader: Any = None
        self._finbert: Any = None
        self._hf_client: Any = None
        self._textblob: Any = None
        self._init_models()

    def _init_models(self) -> None:
        if self.use_vader:
            try:
                from utils.local_dependency_loader import configure_nltk_data_path
                configure_nltk_data_path()
                import nltk
                try:
                    nltk.data.find('sentiment/vader_lexicon.zip')
                except LookupError:
                    if os.getenv("NLTK_ALLOW_DOWNLOAD", "").strip().lower() in {"1", "true", "yes"}:
                        nltk.download('vader_lexicon', quiet=True)
                    else:
                        raise

                from nltk.sentiment import SentimentIntensityAnalyzer
                self._vader = SentimentIntensityAnalyzer()
                logger.info("VADER loaded")
            except Exception as e:
                logger.warning("VADER init failed: %s", e)
                self.use_vader = False

        if self.use_finbert:
            # Try Serverless API first if token is available (Free Tier Optimization)
            if self.hf_token:
                try:
                    from huggingface_hub import InferenceClient
                    self._hf_client = InferenceClient(model=self.finbert_model, token=self.hf_token)
                    logger.info("Using HF Inference API for %s", self.finbert_model)
                    return
                except Exception as e:
                    logger.warning("HF InferenceClient init failed: %s", e)

            # Fallback to local transformers
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
                logger.info("FinBERT loaded locally: %s", self.finbert_model)
            except Exception as e:
                logger.warning("FinBERT local init failed: %s", e)
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

        if self.use_finbert:
            finbert_score = 0.0
            finbert_success = False

            # Option A: API
            if self._hf_client:
                try:
                    from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_message
                    @retry(
                        stop=stop_after_attempt(2),
                        wait=wait_exponential(multiplier=1, min=2, max=5),
                        retry=retry_if_exception_message(match=".*loading.*")
                    )
                    def query_api(t):
                        return self._hf_client.text_classification(t[:512])

                    res = query_api(text)
                    if res:
                        best = max(res, key=lambda x: x["score"])
                        label, conf = best["label"], best["score"]
                        finbert_score = conf if label.upper() == "POSITIVE" else -conf if label.upper() == "NEGATIVE" else 0.0
                        finbert_success = True
                except Exception as e:
                    logger.warning("HF API inference error: %s", e)

            # Option B: Local fallback
            if not finbert_success and self._finbert:
                try:
                    r = self._finbert(text[:512])[0]
                    label, conf = r["label"], r["score"]
                    finbert_score = conf if label.upper() == "POSITIVE" else -conf if label.upper() == "NEGATIVE" else 0.0
                    finbert_success = True
                except Exception as e:
                    logger.warning("FinBERT local inference error: %s", e)

            if finbert_success:
                scores[f"finbert_{self.finbert_model.split('/')[-1]}"] = finbert_score
                weights[f"finbert_{self.finbert_model.split('/')[-1]}"] = 0.5

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
