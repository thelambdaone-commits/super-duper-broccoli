import numpy as np
import pytest

from strategies.sentiment_nlp import SentimentAnalyzer


@pytest.fixture
def analyzer() -> SentimentAnalyzer:
    return SentimentAnalyzer(use_deberta=False)


class TestKeywordAnalysis:
    def test_bullish_text(self, analyzer: SentimentAnalyzer) -> None:
        result = analyzer.analyze("Bitcoin is bullish, moon soon!")
        assert result["score"] > 0
        assert result["confidence"] > 0
        assert len(result["matches"]) >= 2

    def test_bearish_text(self, analyzer: SentimentAnalyzer) -> None:
        result = analyzer.analyze("Bearish crash incoming, rug detected")
        assert result["score"] < 0
        assert len(result["matches"]) >= 2

    def test_neutral_text(self, analyzer: SentimentAnalyzer) -> None:
        result = analyzer.analyze("The weather is nice today")
        assert result["score"] == 0.0
        assert result["magnitude"] == 0.0
        assert result["confidence"] == 0.0
        assert result["matches"] == []

    def test_mixed_sentiment(self, analyzer: SentimentAnalyzer) -> None:
        result = analyzer.analyze("Bullish breakout but overbought, be careful")
        assert "bullish" in result["matches"] or "breakout" in result["matches"]
        assert "overbought" in result["matches"]

    def test_single_keyword(self, analyzer: SentimentAnalyzer) -> None:
        result = analyzer.analyze("PUMP!")
        assert result["score"] > 0
        assert result["confidence"] == pytest.approx(0.2)

    def test_case_insensitive(self, analyzer: SentimentAnalyzer) -> None:
        bullish = analyzer.analyze("BULLISH")
        mixed = analyzer.analyze("Bullish")
        assert bullish["score"] == mixed["score"]

    def test_strong_negative(self, analyzer: SentimentAnalyzer) -> None:
        result = analyzer.analyze("Bankruptcy hack exploit rug delist")
        assert result["score"] < -0.3
        assert len(result["matches"]) >= 3


class TestBatchAnalysis:
    def test_batch_empty(self, analyzer: SentimentAnalyzer) -> None:
        results = analyzer.analyze_batch([])
        assert results == []

    def test_batch_multiple(self, analyzer: SentimentAnalyzer) -> None:
        texts = ["Bullish!", "Bearish crash", "Weather is nice"]
        results = analyzer.analyze_batch(texts)
        assert len(results) == 3
        assert results[0]["score"] > 0
        assert results[1]["score"] < 0
        assert results[2]["score"] == 0.0


class TestFeatureVector:
    def test_to_feature_vector(self, analyzer: SentimentAnalyzer) -> None:
        result = {"score": 0.5, "magnitude": 0.3, "confidence": 0.8}
        vec = analyzer.to_feature_vector(result)
        assert isinstance(vec, np.ndarray)
        assert vec.shape == (3,)
        assert vec[0] == 0.5
        assert vec[1] == 0.3
        assert vec[2] == 0.8

    def test_feature_vector_defaults(self, analyzer: SentimentAnalyzer) -> None:
        result = analyzer.analyze("")
        vec = analyzer.to_feature_vector(result)
        assert vec.shape == (3,)

    def test_feature_vector_bullish(self, analyzer: SentimentAnalyzer) -> None:
        result = analyzer.analyze("Bullish breakout!")
        vec = analyzer.to_feature_vector(result)
        assert vec[0] > 0


class TestDeberta:
    def test_fallback_to_keyword_when_not_loaded(self) -> None:
        analyzer = SentimentAnalyzer(use_deberta=True)
        result = analyzer.analyze("Bullish breakout!")
        assert result["score"] > 0

    def test_deberta_disabled_by_default(self) -> None:
        analyzer = SentimentAnalyzer()
        assert analyzer._use_deberta is False
        result = analyzer.analyze("Bullish")
        assert "deberta_raw" not in result
