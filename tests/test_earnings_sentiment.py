import pytest

from utils.earnings_sentiment_pipeline import EarningsSentimentPipeline, EarningsResult
from utils.sentiment_ensemble import SentimentEnsemble


class TestEarningsSentimentPipeline:
    def test_init(self):
        pipeline = EarningsSentimentPipeline()
        assert pipeline is not None
        status = pipeline.get_status()
        assert "hf_model" in status

    def test_analyze_text_sentiment_without_model(self):
        pipeline = EarningsSentimentPipeline(use_huggingface=False)
        result = pipeline.analyze_text_sentiment("The company had a great quarter with strong revenue growth.")
        assert "score" in result
        assert "label" in result
        assert "confidence" in result


class TestSentimentEnsemble:
    def test_ensemble_without_models(self):
        ensemble = SentimentEnsemble(use_vader=False, use_finbert=False, use_textblob=False)
        result = ensemble.analyze("This is great news")
        assert result["ensemble_score"] == 0.0

    def test_ensemble_vader_only(self):
        ensemble = SentimentEnsemble(use_vader=True, use_finbert=False)
        result = ensemble.analyze("This is great news!")
        assert isinstance(result["ensemble_score"], float)

    def test_analyze_batch(self):
        ensemble = SentimentEnsemble(use_vader=True, use_finbert=False)
        results = ensemble.analyze_batch(["Good news", "Bad news", "Neutral statement"])
        assert len(results) == 3
        assert all("ensemble_score" in r for r in results)
