import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from ledger.ledger_db import Ledger, EXECUTION_MODES
from core.signal_executor import _execute_guarded, execute_regex_signal


TEST_DB = ":memory:"


@pytest.fixture
def ledger() -> Ledger:
    return Ledger(db_path=TEST_DB)


@pytest.fixture
def mock_freqai() -> AsyncMock:
    m = AsyncMock()
    m.clob_execute = AsyncMock(return_value={"status": "FILLED", "orderID": "test"})
    return m


@pytest.fixture
def mock_risk() -> MagicMock:
    m = MagicMock()
    m.compute_position_size.return_value = {
        "size": 100.0, "capital_at_risk": 50.0,
        "kelly_pct": 12.5, "net_beta_exposure_pct": 3.2,
    }
    return m


@pytest.fixture
def mock_store() -> MagicMock:
    m = MagicMock()
    m.record_decision = MagicMock()
    m.record_signal = MagicMock()
    return m


class TestExecutionModes:
    def test_valid_modes(self) -> None:
        assert EXECUTION_MODES == {"REPLAY", "PAPER", "SHADOW", "PROD"}

    def test_default_mode(self, ledger: Ledger) -> None:
        mode = ledger.get_execution_mode()
        assert mode == "PAPER"

    def test_set_and_get_mode(self, ledger: Ledger) -> None:
        ledger.set_execution_mode("PROD")
        assert ledger.get_execution_mode() == "PROD"
        ledger.set_execution_mode("REPLAY")
        assert ledger.get_execution_mode() == "REPLAY"

    def test_invalid_mode_raises(self, ledger: Ledger) -> None:
        with pytest.raises(ValueError):
            ledger.set_execution_mode("INVALID")


class TestPaperMode:
    def test_record_paper_order(self, ledger: Ledger) -> None:
        result = ledger.record_paper_order(
            ticker="SOL", side="BUY", price=0.50, size=100.0,
            confidence=0.8, regime_label="LOW_VOLATILITY",
            signal_source="regex",
        )
        assert "position_id" in result
        assert result["ticker"] == "SOL"
        assert result["side"] == "BUY"
        assert result["size"] == 100.0
        assert result["capital_virtual"] == 50.0

    def test_get_paper_positions(self, ledger: Ledger) -> None:
        ledger.record_paper_order("SOL", "BUY", 0.50, 100.0)
        ledger.record_paper_order("BTC", "SELL", 0.60, 50.0)
        positions = ledger.get_paper_positions(status="OPEN")
        assert len(positions) == 2

    def test_close_paper_position(self, ledger: Ledger) -> None:
        result = ledger.record_paper_order("SOL", "BUY", 0.50, 100.0)
        ledger.close_paper_position(result["position_id"])
        open_positions = ledger.get_paper_positions(status="OPEN")
        assert len(open_positions) == 0
        closed_positions = ledger.get_paper_positions(status="CLOSED")
        assert len(closed_positions) == 1


class TestExecuteGuarded:
    @pytest.mark.asyncio
    async def test_replay_mode_skips_execution(
        self, ledger: Ledger, mock_freqai: AsyncMock, mock_store: MagicMock,
    ) -> None:
        await _execute_guarded(
            ticker="SOL", side="BUY", price=0.50, size=100.0,
            confidence=0.8, regime="LOW_VOLATILITY", sizing={},
            ledger=ledger, freqai=mock_freqai, risk=None, store=mock_store,
            mode="REPLAY", signal_source="regex",
        )
        mock_store.record_decision.assert_called_once()
        assert mock_store.record_signal.call_count == 0

    @pytest.mark.asyncio
    async def test_paper_mode_records_virtual(
        self, ledger: Ledger, mock_freqai: AsyncMock, mock_store: MagicMock,
    ) -> None:
        await _execute_guarded(
            ticker="SOL", side="BUY", price=0.50, size=100.0,
            confidence=0.8, regime="LOW_VOLATILITY", sizing={"kelly_pct": 12.5},
            ledger=ledger, freqai=mock_freqai, risk=None, store=mock_store,
            mode="PAPER", signal_source="regex",
        )
        mock_store.record_decision.assert_called_once()
        mock_store.record_signal.assert_called_once()
        paper_positions = ledger.get_paper_positions()
        assert len(paper_positions) == 1
        assert paper_positions[0]["ticker"] == "SOL"

    @pytest.mark.asyncio
    async def test_shadow_mode_executes_mini_size(
        self, ledger: Ledger, mock_freqai: AsyncMock, mock_risk: MagicMock,
        mock_store: MagicMock,
    ) -> None:
        await _execute_guarded(
            ticker="SOL", side="BUY", price=0.50, size=100.0,
            confidence=0.8, regime="LOW_VOLATILITY",
            sizing={"kelly_pct": 12.5, "net_beta_exposure_pct": 3.2},
            ledger=ledger, freqai=mock_freqai, risk=mock_risk, store=mock_store,
            mode="SHADOW", signal_source="regex",
        )
        mock_freqai.clob_execute.assert_called_once()
        call_args = mock_freqai.clob_execute.call_args[1]
        assert call_args["size"] == 1.0
        assert mock_risk.book_exposure.called

    @pytest.mark.asyncio
    async def test_prod_mode_executes_full_size(
        self, ledger: Ledger, mock_freqai: AsyncMock, mock_risk: MagicMock,
        mock_store: MagicMock,
    ) -> None:
        ledger.set_execution_mode("PROD")
        await _execute_guarded(
            ticker="SOL", side="BUY", price=0.50, size=100.0,
            confidence=0.8, regime="LOW_VOLATILITY",
            sizing={"kelly_pct": 12.5, "net_beta_exposure_pct": 3.2},
            ledger=ledger, freqai=mock_freqai, risk=mock_risk, store=mock_store,
            mode="PROD", signal_source="regex",
        )
        mock_freqai.clob_execute.assert_called_once()
        call_args = mock_freqai.clob_execute.call_args[1]
        assert call_args["size"] == 100.0
        assert mock_risk.book_exposure.called

    @pytest.mark.asyncio
    async def test_zero_size_skipped(
        self, ledger: Ledger, mock_freqai: AsyncMock, mock_store: MagicMock,
    ) -> None:
        await _execute_guarded(
            ticker="SOL", side="BUY", price=0.50, size=0.0,
            confidence=0.8, regime="LOW_VOLATILITY", sizing={},
            ledger=ledger, freqai=mock_freqai, risk=None, store=mock_store,
            mode="PROD", signal_source="regex",
        )
        assert not mock_freqai.clob_execute.called
        assert not mock_store.record_decision.called


class TestSignalExecutorModeRouting:
    @pytest.mark.asyncio
    async def test_regex_signal_uses_ledger_mode(
        self, ledger: Ledger, mock_freqai: AsyncMock,
    ) -> None:
        ledger.set_execution_mode("REPLAY")
        await execute_regex_signal(
            signal={"asset": "SOL", "action": "BUY", "price": 0.50, "timestamp": 123},
            ledger=ledger, freqai=mock_freqai,
        )
        assert not mock_freqai.clob_execute.called

    @pytest.mark.asyncio
    async def test_regex_signal_prod_executes(
        self, ledger: Ledger, mock_freqai: AsyncMock,
    ) -> None:
        ledger.set_execution_mode("PROD")
        await execute_regex_signal(
            signal={"asset": "SOL", "action": "BUY", "price": 0.50, "timestamp": 123},
            ledger=ledger, freqai=mock_freqai,
        )
        mock_freqai.clob_execute.assert_called_once()
