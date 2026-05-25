import asyncio
import pytest
from unittest.mock import MagicMock

from services.portfolio_risk_engine import PortfolioRiskEngine, REGIME_SIZING_MULTIPLIER


@pytest.fixture
def mock_ledger() -> MagicMock:
    ledger = MagicMock()
    ledger.get_capital_summary.return_value = {
        "total_capital": 20_000.0,
        "available_capital": 15_000.0,
    }
    return ledger


@pytest.fixture
def engine(mock_ledger: MagicMock) -> PortfolioRiskEngine:
    return PortfolioRiskEngine(ledger=mock_ledger)


class TestKellySizing:
    def test_kelly_nominal(self, engine: PortfolioRiskEngine) -> None:
        size = engine._kelly_size(win_prob=0.55, win_loss_ratio=1.5, capital=20_000.0)
        q = 1.0 - 0.55
        expected_fraction = (0.55 * 1.5 - q) / 1.5  # ~0.25
        capped = min(expected_fraction, 0.25)
        assert size == pytest.approx(20_000.0 * capped)

    def test_kelly_caps_at_kelly_fraction(self, engine: PortfolioRiskEngine) -> None:
        engine.kelly_fraction = 0.15
        size = engine._kelly_size(win_prob=0.9, win_loss_ratio=3.0, capital=10_000.0)
        kelly_raw = (0.9 * 3.0 - 0.1) / 3.0
        capped = min(kelly_raw, 0.15)
        assert size == pytest.approx(10_000.0 * capped)

    def test_kelly_zero_win_prob(self, engine: PortfolioRiskEngine) -> None:
        size = engine._kelly_size(win_prob=0.0, win_loss_ratio=1.5, capital=10_000.0)
        assert size == 0.0

    def test_kelly_win_loss_ratio_zero(self, engine: PortfolioRiskEngine) -> None:
        size = engine._kelly_size(win_prob=0.55, win_loss_ratio=0.0, capital=10_000.0)
        assert size == 0.0

    def test_kelly_win_loss_ratio_negative(self, engine: PortfolioRiskEngine) -> None:
        size = engine._kelly_size(win_prob=0.55, win_loss_ratio=-1.0, capital=10_000.0)
        assert size == 0.0

    def test_kelly_full_certainty(self, engine: PortfolioRiskEngine) -> None:
        size = engine._kelly_size(win_prob=1.0, win_loss_ratio=2.0, capital=10_000.0)
        expected_fraction = (1.0 * 2.0 - 0.0) / 2.0
        capped = min(expected_fraction, 0.25)
        assert size == pytest.approx(10_000.0 * capped)


class TestVolTargetSizing:
    def test_vol_target_nominal(self, engine: PortfolioRiskEngine) -> None:
        size = engine._vol_target_size(capital=20_000.0, asset_vol=0.5)
        expected = min(20_000.0 * 0.15 / 0.5, 20_000.0 * 0.1)
        assert size == pytest.approx(expected)

    def test_vol_target_zero_vol(self, engine: PortfolioRiskEngine) -> None:
        size = engine._vol_target_size(capital=20_000.0, asset_vol=0.0)
        assert size == pytest.approx(20_000.0 * 0.01)

    def test_vol_target_negative_vol(self, engine: PortfolioRiskEngine) -> None:
        size = engine._vol_target_size(capital=20_000.0, asset_vol=-1.0)
        assert size == pytest.approx(20_000.0 * 0.01)


class TestRegimeMultiplier:
    def test_low_volatility(self, engine: PortfolioRiskEngine) -> None:
        m = engine._regime_multiplier("LOW_VOLATILITY", 0.8)
        assert m == pytest.approx(1.0 * 0.8)

    def test_high_trend_volatility(self, engine: PortfolioRiskEngine) -> None:
        m = engine._regime_multiplier("HIGH_TREND_VOLATILITY", 1.0)
        assert m == pytest.approx(0.6 * 1.0)

    def test_erratic_volatility(self, engine: PortfolioRiskEngine) -> None:
        m = engine._regime_multiplier("ERRATIC_VOLATILITY", 0.9)
        assert m == pytest.approx(0.0 * 0.9)

    def test_unknown_regime_default(self, engine: PortfolioRiskEngine) -> None:
        m = engine._regime_multiplier("UNKNOWN_LABEL", 0.7)
        assert m == pytest.approx(0.5 * 0.7)

    def test_zero_confidence(self, engine: PortfolioRiskEngine) -> None:
        m = engine._regime_multiplier("LOW_VOLATILITY", 0.0)
        assert m == 0.0


class TestConcentrationCheck:
    def test_under_limit(self, engine: PortfolioRiskEngine) -> None:
        engine._exposures["SOL"] = 1000.0
        ok = engine._check_concentration("SOL", add_size=2000.0, capital=20_000.0)
        assert ok is True

    def test_at_limit(self, engine: PortfolioRiskEngine) -> None:
        engine._exposures["SOL"] = 5000.0
        ok = engine._check_concentration("SOL", add_size=1000.0, capital=20_000.0)
        assert ok is True

    def test_over_limit(self, engine: PortfolioRiskEngine) -> None:
        engine._exposures["SOL"] = 5000.0
        ok = engine._check_concentration("SOL", add_size=2000.0, capital=20_000.0)
        assert ok is False

    def test_new_asset_under_limit(self, engine: PortfolioRiskEngine) -> None:
        ok = engine._check_concentration("BTC", add_size=5000.0, capital=20_000.0)
        assert ok is True

    def test_new_asset_over_limit(self, engine: PortfolioRiskEngine) -> None:
        ok = engine._check_concentration("BTC", add_size=7000.0, capital=20_000.0)
        assert ok is False


class TestCorrelatedDrawdown:
    def test_under_drawdown_limit(self, engine: PortfolioRiskEngine) -> None:
        ok = engine._check_correlated_drawdown(add_size=1000.0, beta=0.8, capital=20_000.0)
        max_allowed = 0.15 * 20_000.0
        new_net = 0.0 + 1000.0 * 0.8
        assert ok == (new_net <= max_allowed)

    def test_over_drawdown_limit(self, engine: PortfolioRiskEngine) -> None:
        ok = engine._check_correlated_drawdown(add_size=10_000.0, beta=0.8, capital=20_000.0)
        assert ok is False

    def test_zero_beta_no_impact(self, engine: PortfolioRiskEngine) -> None:
        ok = engine._check_correlated_drawdown(add_size=100_000.0, beta=0.0, capital=20_000.0)
        assert ok is True


class TestBookExposure:
    def test_book_buy(self, engine: PortfolioRiskEngine) -> None:
        engine.book_exposure("SOL", 100.0, "BUY")
        assert engine._exposures["SOL"] == 100.0

    def test_book_sell(self, engine: PortfolioRiskEngine) -> None:
        engine.book_exposure("SOL", 50.0, "SELL")
        assert engine._exposures["SOL"] == -50.0

    def test_book_yes(self, engine: PortfolioRiskEngine) -> None:
        engine.book_exposure("BTC", 200.0, "YES")
        assert engine._exposures["BTC"] == 200.0

    def test_book_long(self, engine: PortfolioRiskEngine) -> None:
        engine.book_exposure("ETH", 75.0, "LONG")
        assert engine._exposures["ETH"] == 75.0

    def test_book_multiple_assets(self, engine: PortfolioRiskEngine) -> None:
        engine.book_exposure("SOL", 100.0, "BUY")
        engine.book_exposure("BTC", 50.0, "BUY")
        engine.book_exposure("SOL", 30.0, "SELL")
        assert engine._exposures["SOL"] == 70.0
        assert engine._exposures["BTC"] == 50.0


class TestNetBetaExposure:
    def test_beta_exposure_single_asset(self, engine: PortfolioRiskEngine) -> None:
        engine.book_exposure("SOL", 1000.0, "BUY")
        pct = engine.net_beta_exposure_pct
        total_capital = 20_000.0
        expected = (1000.0 * 0.8) / total_capital * 100
        assert pct == pytest.approx(expected)

    def test_beta_exposure_multiple_assets(self, engine: PortfolioRiskEngine) -> None:
        engine.book_exposure("BTC", 500.0, "BUY")
        engine.book_exposure("SOL", 1000.0, "BUY")
        engine.book_exposure("USDC", 2000.0, "BUY")
        pct = engine.net_beta_exposure_pct
        expected = (500.0 * 1.0 + 1000.0 * 0.8 + 2000.0 * 0.0) / 20_000.0 * 100
        assert pct == pytest.approx(expected)

    def test_beta_exposure_unknown_ticker(self, engine: PortfolioRiskEngine) -> None:
        engine.book_exposure("UNKNOWN", 1000.0, "BUY")
        pct = engine.net_beta_exposure_pct
        expected = (1000.0 * 0.5) / 20_000.0 * 100
        assert pct == pytest.approx(expected)

    def test_beta_exposure_zero_capital(self, engine: PortfolioRiskEngine) -> None:
        engine.ledger.get_capital_summary.return_value = {}
        engine.book_exposure("SOL", 1000.0, "BUY")
        # Fallback is 100.0 USDC
        expected = (1000.0 * 0.8) / 100.0 * 100
        assert engine.net_beta_exposure_pct == pytest.approx(expected)


class TestComputePositionSize:
    def test_real_mode_cap_comes_from_config(self, engine: PortfolioRiskEngine) -> None:
        engine.ledger.get_execution_mode.return_value = "PROD"
        result = engine.compute_position_size(
            ticker="SOL", side="BUY", price=0.50,
            confidence=1.0, win_prob=0.95, win_loss_ratio=5.0,
            regime_label="LOW_VOLATILITY",
        )
        assert result["capital_at_risk"] <= engine.max_real_notional_usdc + 1e-9

    def test_small_live_account_is_raised_to_minimum_viable_trade(self, engine: PortfolioRiskEngine) -> None:
        engine.ledger.get_execution_mode.return_value = "PROD"
        engine.ledger.get_capital_summary.return_value = {
            "total_capital": 16.0,
            "available_capital": 16.0,
        }
        result = engine.compute_position_size(
            ticker="SOL", side="BUY", price=0.50,
            confidence=0.8, regime_label="LOW_VOLATILITY",
        )
        assert result["capital_at_risk"] >= 5.25
        assert result["capital_at_risk"] <= 6.0 + 1e-9

    def test_nominal_compute(self, engine: PortfolioRiskEngine) -> None:
        result = engine.compute_position_size(
            ticker="SOL", side="BUY", price=0.50,
            confidence=0.8, regime_label="LOW_VOLATILITY",
        )
        assert result["size"] > 0
        assert result["capital_at_risk"] == result["size"] * 0.50
        assert result["kelly_pct"] > 0
        assert result["vol_target_pct"] > 0
        assert result["regime_multiplier"] > 0

    def test_erratic_regime_returns_zero(self, engine: PortfolioRiskEngine) -> None:
        result = engine.compute_position_size(
            ticker="SOL", side="BUY", price=0.50,
            confidence=0.9, regime_label="ERRATIC_VOLATILITY",
        )
        assert result["size"] == 0.0
        assert result["regime_multiplier"] == 0.0

    def test_concentration_cap_applied(self, engine: PortfolioRiskEngine) -> None:
        engine._exposures["SOL"] = 5000.0
        result = engine.compute_position_size(
            ticker="SOL", side="BUY", price=0.50,
            confidence=1.0, win_prob=0.9, win_loss_ratio=3.0,
            regime_label="LOW_VOLATILITY",
        )
        max_allowed = engine.max_concentration_pct * 20_000.0
        assert result["size"] <= max_allowed - 5000.0

    def test_drawdown_cap_applied(self, engine: PortfolioRiskEngine) -> None:
        engine.book_exposure("BTC", 10_000.0, "BUY")
        result = engine.compute_position_size(
            ticker="BTC", side="BUY", price=0.50,
            confidence=1.0, win_prob=0.9, win_loss_ratio=3.0,
            regime_label="LOW_VOLATILITY",
        )
        max_dd = engine.max_correlated_drawdown_pct * 20_000.0
        current_net = (10_000.0 * 1.0)
        allowed = (max_dd - current_net) / 1.0
        assert result["size"] <= max(allowed, 0.0)

    def test_zero_price_no_error(self, engine: PortfolioRiskEngine) -> None:
        result = engine.compute_position_size(
            ticker="SOL", side="BUY", price=0.0,
            confidence=0.5, regime_label="LOW_VOLATILITY",
        )
        assert "size" in result
        assert result["capital_at_risk"] == 0.0
        assert result["reason"] == "INVALID_PRICE"

    def test_effective_win_probability_flips_for_sell_side(self, engine: PortfolioRiskEngine) -> None:
        assert engine._effective_win_probability("BUY", 0.80, fallback=0.5) == pytest.approx(0.80)
        assert engine._effective_win_probability("SELL", 0.80, fallback=0.5) == pytest.approx(0.20)
        assert engine._effective_win_probability("NO", 0.65, fallback=0.5) == pytest.approx(0.35)

    def test_validate_signal_risk_uses_side_adjusted_probability(self, engine: PortfolioRiskEngine) -> None:
        ok_buy, reason_buy = asyncio.run(engine.validate_signal_risk(
            {
                "ticker": "SOL",
                "side": "BUY",
                "price": 0.50,
                "confidence": 0.8,
                "predictive_probability": 0.80,
                "regime_label": "LOW_VOLATILITY",
            },
            current_portfolio_value=20_000.0,
            active_positions={},
        ))
        ok_sell, reason_sell = asyncio.run(engine.validate_signal_risk(
            {
                "ticker": "SOL",
                "side": "SELL",
                "price": 0.50,
                "confidence": 0.8,
                "predictive_probability": 0.80,
                "regime_label": "LOW_VOLATILITY",
            },
            current_portfolio_value=20_000.0,
            active_positions={},
        ))
        assert ok_buy is True
        assert reason_buy == "OK"
        assert ok_sell is False
        assert reason_sell == "RISK_CAP_ZERO"

    def test_zero_available_capital_sets_explicit_reason(self, engine: PortfolioRiskEngine) -> None:
        engine.ledger.get_capital_summary.return_value = {
            "total_capital": 20_000.0,
            "available_capital": 0.0,
        }
        result = engine.compute_position_size(
            ticker="SOL", side="BUY", price=0.50,
            confidence=0.8, regime_label="LOW_VOLATILITY",
        )
        assert result["size"] == 0.0
        assert result["reason"] == "INSUFFICIENT_AVAILABLE_CAPITAL"

    def test_available_capital_limits_size(self, engine: PortfolioRiskEngine) -> None:
        engine.ledger.get_capital_summary.return_value = {
            "total_capital": 20_000.0,
            "available_capital": 100.0,
        }
        result = engine.compute_position_size(
            ticker="SOL", side="BUY", price=0.50,
            confidence=1.0, win_prob=0.9, win_loss_ratio=3.0,
            regime_label="LOW_VOLATILITY",
        )
        max_by_avail = 100.0 / 0.50
        assert result["size"] <= max_by_avail

    def test_trailing_drawdown_latches_until_manual_reset(self, engine: PortfolioRiskEngine) -> None:
        engine._peak_equity = 20_000.0
        engine.ledger.get_capital_summary.return_value = {
            "total_capital": 15_000.0,
            "available_capital": 15_000.0,
        }
        tripped = engine.compute_position_size(
            ticker="SOL", side="BUY", price=0.50,
            confidence=1.0, regime_label="LOW_VOLATILITY",
        )
        assert tripped["size"] == 0.0
        assert tripped["reason"].startswith("DRAWDOWN_TRIPPED")

        engine.ledger.get_capital_summary.return_value = {
            "total_capital": 19_900.0,
            "available_capital": 19_900.0,
        }
        still_blocked = engine.compute_position_size(
            ticker="SOL", side="BUY", price=0.50,
            confidence=1.0, regime_label="LOW_VOLATILITY",
        )

        assert still_blocked["size"] == 0.0
        assert still_blocked["reason"].startswith("DRAWDOWN_TRIPPED")

    def test_positive_global_drawdown_limit_trips_by_absolute_value(self, engine: PortfolioRiskEngine) -> None:
        engine.ledger.get_global_drawdown.return_value = 0.25

        result = engine.compute_position_size(
            ticker="SOL", side="BUY", price=0.50,
            confidence=1.0, regime_label="LOW_VOLATILITY",
        )

        assert result["size"] == 0.0
        assert result["reason"].startswith("GLOBAL_DRAWDOWN_TRIPPED")

    def test_hmm_regime_integration(self, engine: PortfolioRiskEngine) -> None:
        result_high = engine.compute_position_size(
            ticker="SOL", side="BUY", price=0.50,
            confidence=1.0, regime_label="HIGH_TREND_VOLATILITY",
        )
        result_low = engine.compute_position_size(
            ticker="SOL", side="BUY", price=0.50,
            confidence=1.0, regime_label="LOW_VOLATILITY",
        )
        assert result_high["size"] < result_low["size"]

    def test_kelly_pct_computed_correctly(self, engine: PortfolioRiskEngine) -> None:
        result = engine.compute_position_size(
            ticker="SOL", side="BUY", price=1.0,
            confidence=0.5, win_prob=0.55, win_loss_ratio=1.5,
            regime_label="LOW_VOLATILITY",
        )
        k = (0.55 * 1.5 - 0.45) / 1.5
        capped = min(k, 0.25)
        expected_kelly_pct = (capped * 20_000.0) / 20_000.0 * 100
        assert result["kelly_pct"] == pytest.approx(expected_kelly_pct)

    def test_aggressive_kelly_is_capped_to_single_position_notional(
        self, engine: PortfolioRiskEngine
    ) -> None:
        result = engine.compute_position_size(
            ticker="SOL", side="BUY", price=0.25,
            confidence=1.0, win_prob=0.95, win_loss_ratio=5.0,
            regime_label="LOW_VOLATILITY",
        )
        max_notional = 20_000.0 * engine.max_single_position_pct
        assert result["capital_at_risk"] <= max_notional + 1e-9
        assert result["single_position_cap_pct"] == pytest.approx(5.0)


class TestHighVolMultiplierConsistency:
    def test_regime_sizing_multiplier_values(self) -> None:
        assert REGIME_SIZING_MULTIPLIER["LOW_VOLATILITY"] == 1.0
        assert REGIME_SIZING_MULTIPLIER["HIGH_TREND_VOLATILITY"] == 0.6
        assert REGIME_SIZING_MULTIPLIER["ERRATIC_VOLATILITY"] == 0.0

    def test_multiplier_affects_final_size(self, engine: PortfolioRiskEngine) -> None:
        result_low = engine.compute_position_size(
            ticker="ETH", side="BUY", price=0.50,
            confidence=1.0, regime_label="LOW_VOLATILITY",
        )
        result_high = engine.compute_position_size(
            ticker="ETH", side="BUY", price=0.50,
            confidence=1.0, regime_label="HIGH_TREND_VOLATILITY",
        )
        expected_ratio = 0.6 / 1.0
        actual_ratio = result_high["size"] / result_low["size"] if result_low["size"] > 0 else 0
        assert actual_ratio == pytest.approx(expected_ratio, rel=0.01)


class TestEdgeCases:
    def test_empty_exposures(self, engine: PortfolioRiskEngine) -> None:
        assert engine.net_beta_exposure_pct == 0.0
        assert engine._exposures == {}

    def test_no_ledger_capital(self, engine: PortfolioRiskEngine) -> None:
        engine.ledger.get_capital_summary.return_value = {
            "total_capital": 0.0,
            "available_capital": 0.0,
        }
        result = engine.compute_position_size(
            ticker="SOL", side="BUY", price=0.50,
            confidence=0.5, regime_label="LOW_VOLATILITY",
        )
        # Fallback 100 * max_single_position_pct 0.05 = 5.0
        assert result["size"] == 5.0
        assert result["kelly_pct"] == 25.0

    def test_ticker_with_dash_prefix(self, engine: PortfolioRiskEngine) -> None:
        engine.book_exposure("BTC-PERP", 500.0, "BUY")
        assert engine._exposures["BTC"] == 500.0
        pct = engine.net_beta_exposure_pct
        expected = (500.0 * 1.0) / 20_000.0 * 100
        assert pct == pytest.approx(expected)
