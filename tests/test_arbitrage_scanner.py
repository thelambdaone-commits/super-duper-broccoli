import pytest

from strategies.arbitrage_scanner import (
    ArbitrageScanner, MISPRICING_ZSCORE_THRESHOLD,
)


@pytest.fixture
def scanner() -> ArbitrageScanner:
    return ArbitrageScanner(min_profit_threshold=0.02)


class TestSumInefficiency:
    def test_nominal_detection(self, scanner: ArbitrageScanner) -> None:
        markets = {
            "mkt-1": {"YES": 0.55, "NO": 0.55},
        }
        opportunities = scanner.scan_sum_inefficiency(markets)
        assert len(opportunities) == 1
        opp = opportunities[0]
        assert opp["type"] == "sum_inefficiency"
        assert opp["market_id"] == "mkt-1"
        assert opp["total_probability"] == pytest.approx(1.10)
        assert opp["deviation"] == pytest.approx(0.10)
        assert opp["action"] == "SELL"

    def test_no_inefficiency(self, scanner: ArbitrageScanner) -> None:
        markets = {
            "mkt-2": {"YES": 0.50, "NO": 0.49},
        }
        opportunities = scanner.scan_sum_inefficiency(markets)
        assert len(opportunities) == 0

    def test_underpriced_under_1(self, scanner: ArbitrageScanner) -> None:
        markets = {
            "mkt-3": {"YES": 0.40, "NO": 0.40},
        }
        opportunities = scanner.scan_sum_inefficiency(markets)
        assert len(opportunities) == 1
        assert opportunities[0]["total_probability"] == pytest.approx(0.80)

    def test_multiple_markets(self, scanner: ArbitrageScanner) -> None:
        markets = {
            "mkt-4": {"YES": 0.60, "NO": 0.45},
            "mkt-5": {"YES": 0.50, "NO": 0.49},
            "mkt-6": {"YES": 0.30, "NO": 0.30},
        }
        opportunities = scanner.scan_sum_inefficiency(markets)
        assert len(opportunities) == 2

    def test_confidence_scales_with_deviation(self, scanner: ArbitrageScanner) -> None:
        markets = {
            "mkt-7": {"YES": 0.80, "NO": 0.30},
        }
        opportunities = scanner.scan_sum_inefficiency(markets)
        assert opportunities[0]["confidence"] > 0.5

    def test_empty_markets(self, scanner: ArbitrageScanner) -> None:
        opportunities = scanner.scan_sum_inefficiency({})
        assert opportunities == []


class TestConditionalOverpricing:
    def test_child_overpriced(self, scanner: ArbitrageScanner) -> None:
        opportunities = scanner.scan_conditional_overpricing(
            parent_market_id="parent-1",
            parent_prob=0.50,
            child_outcomes={"YES": 0.55, "NO": 0.45},
        )
        assert len(opportunities) == 1
        opp = opportunities[0]
        assert opp["type"] == "conditional_overpricing"
        assert opp["action"] == "SELL"
        assert opp["excess"] == pytest.approx(0.05)

    def test_no_overpricing(self, scanner: ArbitrageScanner) -> None:
        opportunities = scanner.scan_conditional_overpricing(
            parent_market_id="parent-2",
            parent_prob=0.60,
            child_outcomes={"YES": 0.55, "NO": 0.30},
        )
        assert len(opportunities) == 0

    def test_multiple_children(self, scanner: ArbitrageScanner) -> None:
        opportunities = scanner.scan_conditional_overpricing(
            parent_market_id="parent-3",
            parent_prob=0.40,
            child_outcomes={"A": 0.50, "B": 0.45, "C": 0.35},
        )
        assert len(opportunities) == 2

    def test_empty_children(self, scanner: ArbitrageScanner) -> None:
        opportunities = scanner.scan_conditional_overpricing(
            parent_market_id="parent-4",
            parent_prob=0.50,
            child_outcomes={},
        )
        assert opportunities == []


class TestMispricingIPV:
    def _seed(self, scanner: ArbitrageScanner, market: str, base: float, n: int = 20, noise: float = 0.02) -> None:
        import random
        rng = random.Random(42)
        for _ in range(n):
            scanner.record_price(market, base + rng.uniform(-noise, noise))

    def test_insufficient_history_returns_empty(self, scanner: ArbitrageScanner) -> None:
        opps = scanner.scan_mispricing({"mkt-1": 0.50})
        assert opps == []

    def test_detects_high_zscore(self, scanner: ArbitrageScanner) -> None:
        self._seed(scanner, "mkt-2", 0.50)
        opps = scanner.scan_mispricing({"mkt-2": 0.65})
        assert len(opps) >= 1
        assert opps[0]["type"] == "mispricing_ipv"
        assert opps[0]["action"] == "SELL"
        assert opps[0]["zscore"] > MISPRICING_ZSCORE_THRESHOLD

    def test_detects_low_zscore(self, scanner: ArbitrageScanner) -> None:
        self._seed(scanner, "mkt-3", 0.50)
        opps = scanner.scan_mispricing({"mkt-3": 0.35})
        assert len(opps) >= 1
        assert opps[0]["action"] == "BUY"

    def test_no_mispricing_within_threshold(self, scanner: ArbitrageScanner) -> None:
        self._seed(scanner, "mkt-4", 0.50, n=30)
        opps = scanner.scan_mispricing({"mkt-4": 0.50})
        assert opps == []

    def test_sma_computed(self, scanner: ArbitrageScanner) -> None:
        self._seed(scanner, "mkt-5", 0.50, n=50)
        opps = scanner.scan_mispricing({"mkt-5": 0.60})
        assert opps[0]["short_ma"] is not None
        assert opps[0]["long_ma"] is not None

    def test_trend_residual(self, scanner: ArbitrageScanner) -> None:
        for i in range(20):
            scanner.record_price("mkt-6", 0.40 + i * 0.01)
        opps = scanner.scan_mispricing({"mkt-6": 0.65})
        assert opps[0]["trend_residual_pct"] is not None

    def test_confidence_scales_with_deviation(self, scanner: ArbitrageScanner) -> None:
        self._seed(scanner, "mkt-7", 0.50)
        small = scanner.scan_mispricing({"mkt-7": 0.55})
        self._seed(scanner, "mkt-8", 0.50)
        large = scanner.scan_mispricing({"mkt-8": 0.80})
        assert large[0]["confidence"] > small[0]["confidence"]

    def test_multiple_markets_independent(self, scanner: ArbitrageScanner) -> None:
        self._seed(scanner, "mkt-a", 0.50)
        self._seed(scanner, "mkt-b", 0.30)
        opps = scanner.scan_mispricing({"mkt-a": 0.65, "mkt-b": 0.31})
        assert len(opps) >= 1
        mkt_ids = [o["market_id"] for o in opps]
        assert "mkt-a" in mkt_ids

    def test_records_price_on_scan(self, scanner: ArbitrageScanner) -> None:
        self._seed(scanner, "mkt-9", 0.50, n=20, noise=0.0)
        before = len(scanner._price_history["mkt-9"])
        scanner.scan_mispricing({"mkt-9": 0.55})
        assert len(scanner._price_history["mkt-9"]) == before + 1

    def test_clear_price_history_market(self, scanner: ArbitrageScanner) -> None:
        self._seed(scanner, "mkt-10", 0.50, n=10)
        self._seed(scanner, "other", 0.30, n=10)
        scanner.clear_price_history("mkt-10")
        assert "mkt-10" not in scanner._price_history
        assert "other" in scanner._price_history

    def test_clear_price_history_all(self, scanner: ArbitrageScanner) -> None:
        self._seed(scanner, "mkt-a", 0.50, n=10)
        self._seed(scanner, "mkt-b", 0.30, n=10)
        scanner.clear_price_history()
        assert len(scanner._price_history) == 0


class TestToSignals:
    def test_sum_inefficiency_to_signal(self, scanner: ArbitrageScanner) -> None:
        opportunities = scanner.scan_sum_inefficiency({
            "mkt-1": {"YES": 0.55, "NO": 0.55},
        })
        signals = scanner.to_signals(opportunities)
        assert len(signals) == 1
        signal = signals[0]
        assert signal["source"] == "arbitrage"
        assert signal["asset"] == "mkt-1"
        assert signal["action"] == "SELL"
        assert signal["confidence"] > 0

    def test_conditional_to_signal(self, scanner: ArbitrageScanner) -> None:
        opportunities = scanner.scan_conditional_overpricing(
            parent_market_id="parent-1",
            parent_prob=0.50,
            child_outcomes={"YES": 0.60},
        )
        signals = scanner.to_signals(opportunities)
        assert len(signals) == 1
        assert signals[0]["source"] == "arbitrage"
        assert signals[0]["arb_type"] == "conditional_overpricing"

    def test_mispricing_to_signal(self, scanner: ArbitrageScanner) -> None:
        for _ in range(20):
            scanner.record_price("mkt-99", 0.50)
        opps = scanner.scan_mispricing({"mkt-99": 0.70})
        signals = scanner.to_signals(opps)
        assert len(signals) == 1
        assert signals[0]["source"] == "arbitrage"
        assert signals[0]["arb_type"] == "mispricing_ipv"
        assert signals[0]["zscore"] is not None

    def test_empty_opportunities(self, scanner: ArbitrageScanner) -> None:
        signals = scanner.to_signals([])
        assert signals == []


class TestOpportunityManagement:
    def test_accumulation(self, scanner: ArbitrageScanner) -> None:
        scanner.scan_sum_inefficiency({"mkt-1": {"YES": 0.60, "NO": 0.50}})
        scanner.scan_conditional_overpricing("p", 0.50, {"YES": 0.60})
        assert scanner.opportunity_count == 2

    def test_clear(self, scanner: ArbitrageScanner) -> None:
        scanner.scan_sum_inefficiency({"mkt-1": {"YES": 0.60, "NO": 0.50}})
        assert scanner.clear_opportunities() == 1
        assert scanner.opportunity_count == 0

    def test_get_active(self, scanner: ArbitrageScanner) -> None:
        scanner.scan_sum_inefficiency({"mkt-1": {"YES": 0.60, "NO": 0.50}})
        active = scanner.get_active_opportunities()
        assert len(active) == 1
        assert active[0]["market_id"] == "mkt-1"


class TestThreshold:
    def test_custom_threshold(self) -> None:
        s = ArbitrageScanner(min_profit_threshold=0.10)
        opps = s.scan_sum_inefficiency({"mkt": {"YES": 0.55, "NO": 0.52}})
        assert len(opps) == 0

    def test_low_threshold_detects_small_arb(self) -> None:
        s = ArbitrageScanner(min_profit_threshold=0.01)
        opps = s.scan_sum_inefficiency({"mkt": {"YES": 0.51, "NO": 0.51}})
        assert len(opps) == 1
