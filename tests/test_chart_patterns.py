import pytest

from utils.chart_pattern_detector import ChartPatternDetector


class TestChartPatternDetector:
    def test_init(self):
        detector = ChartPatternDetector()
        assert detector is not None

    def test_supported_patterns(self):
        detector = ChartPatternDetector()
        patterns = detector.get_supported_patterns()
        assert len(patterns) > 0
        assert "Head and shoulders top" in patterns

    def test_detect_from_array_no_model(self):
        detector = ChartPatternDetector()
        detector._model = None
        ohlcv = [
            {"Open": 100, "High": 105, "Low": 99, "Close": 104, "Volume": 1000},
            {"Open": 104, "High": 108, "Low": 103, "Close": 107, "Volume": 1200},
            {"Open": 107, "High": 110, "Low": 106, "Close": 109, "Volume": 900},
        ]
        results = detector.detect_from_array(ohlcv)
        assert len(results) == 1
        assert "error" in results[0]
