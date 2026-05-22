import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.signal_executor import _execution_succeeded, _extract_fill_confirmation, _regex_confidence
from core.signal_executor import execute_regex_signal, execute_lobstar_signal


class TestExecutionSucceeded:
    def test_none_result(self) -> None:
        assert _execution_succeeded(None) is False

    def test_empty_result(self) -> None:
        assert _execution_succeeded({}) is False

    def test_rejected_status(self) -> None:
        assert _execution_succeeded({"status": "REJECTED"}) is False

    def test_post_only_rejected(self) -> None:
        assert _execution_succeeded({"status": "POST_ONLY_REJECTED"}) is False

    def test_cancel_failed(self) -> None:
        assert _execution_succeeded({"status": "CANCEL_FAILED"}) is False

    def test_error_status(self) -> None:
        assert _execution_succeeded({"status": "ERROR"}) is False

    def test_filled_status(self) -> None:
        assert _execution_succeeded({"status": "FILLED"}) is True

    def test_taker_filled_status(self) -> None:
        assert _execution_succeeded({"status": "TAKER_FILLED"}) is True

    def test_matched_status(self) -> None:
        assert _execution_succeeded({"status": "MATCHED"}) is True

    def test_live_status(self) -> None:
        assert _execution_succeeded({"status": "LIVE"}) is True

    def test_delayed_status(self) -> None:
        assert _execution_succeeded({"status": "DELAYED"}) is True

    def test_has_order_id(self) -> None:
        assert _execution_succeeded({"orderID": "abc-123"}) is True

    def test_has_order_id_alt_key(self) -> None:
        assert _execution_succeeded({"order_id": "abc-123"}) is True

    def test_unknown_status_no_order_id(self) -> None:
        assert _execution_succeeded({"status": "SOMETHING_ELSE"}) is False


class TestFillExtraction:
    def test_partial_fill_uses_reported_size(self) -> None:
        confirmation = {
            "status": "PARTIAL",
            "filled_size": "3.5",
            "price": "0.45",
            "orderID": "ord-1",
        }

        fill = _extract_fill_confirmation(confirmation, requested_size=10.0, requested_price=0.5)

        assert fill["filled_size"] == 3.5
        assert fill["filled_price"] == 0.45
        assert fill["status"] == "PARTIAL"

    def test_rejected_fill_returns_zero(self) -> None:
        fill = _extract_fill_confirmation({"status": "REJECTED"}, requested_size=10.0, requested_price=0.5)

        assert fill["filled_size"] == 0.0
        assert fill["filled_price"] == 0.5


class TestRegexConfidence:
    def test_no_significant_decimals(self) -> None:
        c = _regex_confidence(0.0, decimals=4)
        assert c == 0.5

    def test_zero_price(self) -> None:
        c = _regex_confidence(0.0, decimals=4)
        assert c == 0.5

    def test_one_significant_decimal(self) -> None:
        c = _regex_confidence(0.5, decimals=4)
        assert c == 0.6

    def test_two_significant_decimals(self) -> None:
        c = _regex_confidence(0.55, decimals=4)
        assert c == 0.7

    def test_max_cap(self) -> None:
        c = _regex_confidence(0.5555, decimals=4)
        assert c == 0.85

    def test_four_significant_decimals(self) -> None:
        c = _regex_confidence(0.1234, decimals=4)
        assert c == 0.85

    def test_trailing_zeros_ignored(self) -> None:
        c = _regex_confidence(0.5000, decimals=4)
        assert c == 0.6

    def test_integer_price(self) -> None:
        c = _regex_confidence(50, decimals=4)
        assert c == 0.5


class MockLedger:
    def __init__(self, mode: str = "PAPER") -> None:
        self._mode = mode
        self.recorded_orders: list[dict] = []
        self.recorded_paper_orders: list[dict] = []

    def get_execution_mode(self) -> str:
        return self._mode

    def validate_and_reserve(self, **kwargs) -> dict:
        return {"authorized": True, "size": kwargs.get("requested_size", 100), "reason": "ok"}

    def record_paper_order(self, **kwargs) -> dict:
        self.recorded_paper_orders.append(dict(kwargs))
        return {"position_id": "paper-1", **kwargs}

    def record_order(self, **kwargs) -> None:
        self.recorded_orders.append(dict(kwargs))

    def get_paper_positions(self, **kwargs) -> list:
        return []

    def close_paper_position(self, position_id: str) -> None:
        pass

    def set_execution_mode(self, mode: str) -> None:
        self._mode = mode


def _attach_benign_order_book(freqai) -> None:
    freqai.client = MagicMock()
    freqai.client.get_order_book.return_value = {
        "bids": [{"price": 0.49}],
        "asks": [{"price": 0.51}],
    }


class TestExecuteRegexSignal:
    @pytest.mark.asyncio
    async def test_replay_mode_skips_clob(self) -> None:
        ledger = MockLedger(mode="REPLAY")
        signal = {"asset": "SOL", "action": "BUY", "price": 0.50, "timestamp": 123}
        freqai = AsyncMock()
        _attach_benign_order_book(freqai)

        await execute_regex_signal(signal=signal, ledger=ledger, freqai=freqai)

        freqai.clob_execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_paper_mode_records_virtual(self) -> None:
        ledger = MockLedger(mode="PAPER")
        signal = {"asset": "SOL", "action": "BUY", "price": 0.50, "timestamp": 123}
        freqai = AsyncMock()
        _attach_benign_order_book(freqai)

        await execute_regex_signal(signal=signal, ledger=ledger, freqai=freqai)

        freqai.clob_execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_prod_mode_calls_execute(self) -> None:
        ledger = MockLedger(mode="PROD")
        signal = {"asset": "SOL", "action": "BUY", "price": 0.50, "timestamp": 123}
        freqai = AsyncMock()
        _attach_benign_order_book(freqai)
        freqai.clob_execute = AsyncMock(return_value={
            "status": "FILLED", "orderID": "ord-1", "filled_size": 7.0, "price": 0.50,
        })

        await execute_regex_signal(signal=signal, ledger=ledger, freqai=freqai)

        freqai.clob_execute.assert_called_once()
        assert ledger.recorded_orders[0]["size"] == 7.0
        assert ledger.recorded_orders[0]["price"] == 0.50

    @pytest.mark.asyncio
    async def test_prod_blocked_by_ledger(self) -> None:
        ledger = MockLedger(mode="PROD")
        signal = {"asset": "SOL", "action": "BUY", "price": 0.50, "timestamp": 123}
        freqai = AsyncMock()
        _attach_benign_order_book(freqai)
        expected_reason = "account_limit_exceeded"

        with patch.object(ledger, "validate_and_reserve", return_value={
            "authorized": False, "size": 0, "reason": expected_reason,
        }):
            await execute_regex_signal(signal=signal, ledger=ledger, freqai=freqai)

        freqai.clob_execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_paper_with_risk_engine(self) -> None:
        ledger = MockLedger(mode="PAPER")
        signal = {"asset": "SOL", "action": "BUY", "price": 0.50, "timestamp": 123}
        freqai = AsyncMock()
        _attach_benign_order_book(freqai)
        risk = MagicMock()
        risk.compute_position_size.return_value = {
            "size": 100.0, "capital_at_risk": 50.0,
            "kelly_pct": 12.5, "net_beta_exposure_pct": 3.2,
        }

        await execute_regex_signal(signal=signal, ledger=ledger, freqai=freqai, risk=risk)

        risk.compute_position_size.assert_called_once()
        assert risk.book_exposure.called

    @pytest.mark.asyncio
    async def test_executor_passed_through_for_prod(self) -> None:
        ledger = MockLedger(mode="PROD")
        signal = {"asset": "SOL", "action": "BUY", "price": 0.50, "timestamp": 123}
        freqai = AsyncMock()
        _attach_benign_order_book(freqai)
        executor = AsyncMock()
        executor.execute = AsyncMock(return_value={
            "status": "FILLED", "execution_path": "maker", "order_id": "ord-1", "filled_size": 4.0, "price": 0.50,
        })

        await execute_regex_signal(
            signal=signal, ledger=ledger, freqai=freqai, executor=executor,
        )

        executor.execute.assert_called_once()
        assert ledger.recorded_orders[0]["size"] == 4.0

    @pytest.mark.asyncio
    async def test_zero_fill_does_not_persist(self) -> None:
        ledger = MockLedger(mode="PROD")
        signal = {"asset": "SOL", "action": "BUY", "price": 0.50, "timestamp": 123}
        freqai = AsyncMock()
        _attach_benign_order_book(freqai)
        freqai.clob_execute = AsyncMock(return_value={
            "status": "FILLED", "orderID": "ord-1", "filled_size": 0.0, "price": 0.50,
        })

        result = await execute_regex_signal(signal=signal, ledger=ledger, freqai=freqai)

        assert result["status"] == "FAILED"
        assert ledger.recorded_orders == []

    @pytest.mark.asyncio
    async def test_unknown_live_mode_still_uses_slippage_gate(self) -> None:
        ledger = MockLedger(mode="LIVE_CANARY")
        signal = {"asset": "SOL", "action": "BUY", "price": 0.50, "timestamp": 123}
        freqai = AsyncMock()
        freqai.client = MagicMock()
        freqai.client.get_order_book.return_value = {
            "bids": [{"price": 0.90}],
            "asks": [{"price": 0.92}],
        }

        result = await execute_regex_signal(signal=signal, ledger=ledger, freqai=freqai)

        assert result["status"] == "SKIPPED"
        assert "Slippage threshold exceeded" in result["reason"]
        freqai.clob_execute.assert_not_called()


class TestExecuteLobstarSignal:
    @pytest.mark.asyncio
    async def test_none_decision_skipped(self) -> None:
        signal = {"raw": "some text", "timestamp": 123}
        lobstar = AsyncMock()
        lobstar.analyser_signal_contextuel = AsyncMock(return_value=None)
        ledger = MockLedger()
        freqai = AsyncMock()
        _attach_benign_order_book(freqai)

        await execute_lobstar_signal(
            signal=signal, ledger=ledger, freqai=freqai, lobstar=lobstar,
        )

        freqai.clob_execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_incomplete_decision_skipped(self) -> None:
        signal = {"raw": "some text", "timestamp": 123}
        lobstar = AsyncMock()
        lobstar.analyser_signal_contextuel = AsyncMock(return_value={
            "ticker": "", "side": "BUY", "price_limite": 0.50, "size": 100, "confidence": 0.8,
        })
        ledger = MockLedger()
        freqai = AsyncMock()
        _attach_benign_order_book(freqai)

        await execute_lobstar_signal(
            signal=signal, ledger=ledger, freqai=freqai, lobstar=lobstar,
        )

        freqai.clob_execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_low_confidence_skipped(self) -> None:
        signal = {"raw": "some text", "timestamp": 123}
        lobstar = AsyncMock()
        lobstar.analyser_signal_contextuel = AsyncMock(return_value={
            "ticker": "SOL", "side": "BUY", "price_limite": 0.50, "size": 100, "confidence": 0.2,
        })
        ledger = MockLedger()
        freqai = AsyncMock()
        _attach_benign_order_book(freqai)

        await execute_lobstar_signal(
            signal=signal, ledger=ledger, freqai=freqai, lobstar=lobstar,
        )

        freqai.clob_execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_price_skipped(self) -> None:
        signal = {"raw": "some text", "timestamp": 123}
        lobstar = AsyncMock()
        lobstar.analyser_signal_contextuel = AsyncMock(return_value={
            "ticker": "SOL", "side": "BUY", "price_limite": 0.0, "size": 100, "confidence": 0.8,
        })
        ledger = MockLedger()
        freqai = AsyncMock()
        _attach_benign_order_book(freqai)

        await execute_lobstar_signal(
            signal=signal, ledger=ledger, freqai=freqai, lobstar=lobstar,
        )

        freqai.clob_execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_valid_decision_prod_executes(self) -> None:
        signal = {"raw": "some text", "timestamp": 123}
        lobstar = AsyncMock()
        lobstar.analyser_signal_contextuel = AsyncMock(return_value={
            "ticker": "SOL", "side": "BUY", "price_limite": 0.50, "size": 100, "confidence": 0.8,
        })
        ledger = MockLedger(mode="PROD")
        freqai = AsyncMock()
        _attach_benign_order_book(freqai)
        freqai.clob_execute = AsyncMock(return_value={"status": "FILLED", "orderID": "ord-1"})

        await execute_lobstar_signal(
            signal=signal, ledger=ledger, freqai=freqai, lobstar=lobstar,
        )

        freqai.clob_execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_valid_decision_paper_mode(self) -> None:
        signal = {"raw": "some text", "timestamp": 123}
        lobstar = AsyncMock()
        lobstar.analyser_signal_contextuel = AsyncMock(return_value={
            "ticker": "SOL", "side": "BUY", "price_limite": 0.50, "size": 100, "confidence": 0.8,
        })
        ledger = MockLedger(mode="PAPER")
        freqai = AsyncMock()
        _attach_benign_order_book(freqai)

        await execute_lobstar_signal(
            signal=signal, ledger=ledger, freqai=freqai, lobstar=lobstar,
        )

        freqai.clob_execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_lobstar_confidence_edge_case(self) -> None:
        signal = {"raw": "edge case", "timestamp": 123}
        lobstar = AsyncMock()
        lobstar.analyser_signal_contextuel = AsyncMock(return_value={
            "ticker": "SOL", "side": "BUY", "price_limite": 0.50, "size": 100, "confidence": 0.3,
        })
        ledger = MockLedger(mode="PROD")
        freqai = AsyncMock()
        _attach_benign_order_book(freqai)
        freqai.clob_execute = AsyncMock(return_value={"status": "FILLED", "orderID": "ord-1"})

        await execute_lobstar_signal(
            signal=signal, ledger=ledger, freqai=freqai, lobstar=lobstar,
        )

        freqai.clob_execute.assert_called_once()
