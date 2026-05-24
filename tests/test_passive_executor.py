import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from polymarket.execution.passive_executor import PassiveExecutor


@pytest.fixture
def mock_freqai() -> AsyncMock:
    m = AsyncMock()
    m.post_order = AsyncMock()
    m.create_order = AsyncMock()
    m.cancel_order = AsyncMock()
    m.get_order_status = AsyncMock()
    return m


@pytest.fixture
def executor(mock_freqai: AsyncMock) -> PassiveExecutor:
    return PassiveExecutor(
        freqai=mock_freqai,
        maker_timeout_seconds=0.2,
        poll_interval=0.05,
        post_only=True,
    )


@pytest.fixture
def wallet_manager_mock() -> AsyncMock:
    wallet_manager = AsyncMock()
    wallet_manager.ensure_usdc_allowance = AsyncMock(return_value={"approved": True, "action": "noop", "allowance": 1000.0})
    return wallet_manager


class TestMakerFirst:
    @pytest.mark.asyncio
    async def test_maker_filled_immediately(
        self, executor: PassiveExecutor, mock_freqai: AsyncMock,
    ) -> None:
        mock_freqai.post_order.return_value = {"status": "OK", "orderID": "ord-1"}
        mock_freqai.get_order_status.return_value = {
            "status": "OK",
            "order": {"remaining_size": 0, "size": 100},
        }

        result = await executor.execute("SOL", "BUY", 0.50, 100.0)

        assert result["status"] == "FILLED"
        assert result["order_id"] == "ord-1"
        assert result["execution_path"] == "maker"
        assert executor.fill_count == 1

    @pytest.mark.asyncio
    async def test_maker_rejected_falls_back_to_taker(
        self, executor: PassiveExecutor, mock_freqai: AsyncMock,
    ) -> None:
        mock_freqai.post_order.return_value = {
            "status": "POST_ONLY_REJECTED",
            "error": "post only would match",
        }
        mock_freqai.create_order.return_value = {"status": "FILLED", "orderID": "ord-taker"}

        result = await executor.execute("SOL", "BUY", 0.50, 100.0)

        assert result["status"] == "TAKER_FILLED"
        assert result["execution_path"] == "taker"
        assert executor.reject_count == 1

    @pytest.mark.asyncio
    async def test_maker_timeout_falls_back_to_taker(
        self, executor: PassiveExecutor, mock_freqai: AsyncMock,
    ) -> None:
        mock_freqai.post_order.return_value = {"status": "OK", "orderID": "ord-2"}
        mock_freqai.get_order_status.return_value = {
            "status": "OK",
            "order": {"remaining_size": 100, "size": 100},
        }
        mock_freqai.cancel_order.return_value = {"status": "CANCELLED"}
        mock_freqai.create_order.return_value = {"status": "FILLED", "orderID": "ord-taker"}

        result = await executor.execute("SOL", "BUY", 0.50, 100.0)

        assert result["status"] == "TAKER_FILLED"
        assert result["execution_path"] == "taker"
        assert executor.taker_fallback_count == 1
        mock_freqai.cancel_order.assert_called_once_with("ord-2")

    @pytest.mark.asyncio
    async def test_maker_no_order_id_falls_back(
        self, executor: PassiveExecutor, mock_freqai: AsyncMock,
    ) -> None:
        mock_freqai.post_order.return_value = {"status": "OK"}
        mock_freqai.create_order.return_value = {"status": "FILLED", "orderID": "ord-taker"}

        result = await executor.execute("SOL", "BUY", 0.50, 100.0)

        assert result["status"] == "TAKER_FILLED"
        assert executor.reject_count == 1

    @pytest.mark.asyncio
    async def test_maker_local_sizing_reject_does_not_fall_back_to_taker(
        self, executor: PassiveExecutor, mock_freqai: AsyncMock,
    ) -> None:
        mock_freqai.post_order.side_effect = ValueError(
            "[Sizing] Ordre rejete: notionnel (0.61) < minimum Polymarket (5.00)"
        )

        result = await executor.execute("SOL", "BUY", 0.50, 1.0)

        assert result["status"] == "REJECTED_SIZING"
        assert result["execution_path"] == "maker"
        mock_freqai.create_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_maker_cancel_fails_still_falls_back(
        self, executor: PassiveExecutor, mock_freqai: AsyncMock,
    ) -> None:
        mock_freqai.post_order.return_value = {"status": "OK", "orderID": "ord-3"}
        mock_freqai.get_order_status.return_value = {
            "status": "OK",
            "order": {"remaining_size": 50, "size": 100},
        }
        mock_freqai.cancel_order.return_value = {"status": "CANCEL_FAILED", "error": "network"}
        mock_freqai.create_order.return_value = {"status": "FILLED", "orderID": "ord-taker"}

        result = await executor.execute("SOL", "BUY", 0.50, 100.0)

        assert result["execution_path"] == "taker"

    @pytest.mark.asyncio
    async def test_get_order_status_returns_filled_directly(
        self, executor: PassiveExecutor, mock_freqai: AsyncMock,
    ) -> None:
        mock_freqai.post_order.return_value = {"status": "OK", "orderID": "ord-4"}
        mock_freqai.get_order_status.return_value = {"status": "FILLED"}

        result = await executor.execute("SOL", "BUY", 0.50, 100.0)

        assert result["status"] == "FILLED"
        assert executor.fill_count == 1


class TestTakerOnly:
    @pytest.mark.asyncio
    async def test_taker_without_maker(
        self, mock_freqai: AsyncMock,
    ) -> None:
        exec_taker = PassiveExecutor(
            freqai=mock_freqai, post_only=False,
        )
        mock_freqai.create_order.return_value = {"status": "FILLED", "orderID": "ord-taker"}

        result = await exec_taker.execute("SOL", "BUY", 0.50, 100.0)

        assert result["execution_path"] == "taker"
        mock_freqai.post_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_taker_failure(
        self, executor: PassiveExecutor, mock_freqai: AsyncMock,
    ) -> None:
        mock_freqai.post_order.return_value = {
            "status": "POST_ONLY_REJECTED",
            "error": "would match",
        }
        mock_freqai.create_order.side_effect = Exception("CLOB timeout")

        result = await executor.execute("SOL", "BUY", 0.50, 100.0)

        assert result["status"] == "TAKER_FAILED"
        assert "error" in result

    @pytest.mark.asyncio
    async def test_taker_local_reject_does_not_report_fill(
        self, executor: PassiveExecutor, mock_freqai: AsyncMock,
    ) -> None:
        mock_freqai.post_order.return_value = {
            "status": "POST_ONLY_REJECTED",
            "error": "would match",
        }
        mock_freqai.create_order.return_value = {
            "status": "LOCAL_REJECT_MIN_NOTIONAL",
            "error": "below min notional",
        }

        result = await executor.execute("SOL", "BUY", 0.50, 1.0)

        assert result["status"] == "TAKER_FAILED"
        assert result["execution_path"] == "taker"
        assert result["error"] == "below min notional"

    @pytest.mark.asyncio
    async def test_maker_local_reject_does_not_fallback_to_taker(
        self, executor: PassiveExecutor, mock_freqai: AsyncMock,
    ) -> None:
        mock_freqai.post_order.return_value = {
            "status": "REJECTED",
            "error": "token_id invalide ou marché indisponible",
        }

        result = await executor.execute("SOL", "BUY", 0.50, 1.0)

        assert result["status"] == "REJECTED"
        assert result["execution_path"] == "maker"
        assert "marché indisponible" in result["error"]
        mock_freqai.create_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_taker_returns_executed_price(
        self, executor: PassiveExecutor, mock_freqai: AsyncMock,
    ) -> None:
        mock_freqai.post_order.return_value = {
            "status": "POST_ONLY_REJECTED",
            "error": "would match",
        }
        mock_freqai.create_order.return_value = {"status": "FILLED", "orderID": "ord-taker"}

        result = await executor.execute("SOL", "BUY", 100.0, 1.0)

        assert result["status"] == "TAKER_FILLED"
        assert result["price"] != 100.0
        assert result["price"] > 100.0
        assert result["target_price"] == 100.0

    @pytest.mark.asyncio
    async def test_taker_prod_uses_requested_price_without_simulation(
        self, mock_freqai: AsyncMock,
    ) -> None:
        ledger = Mock()
        ledger.get_execution_mode.return_value = "PROD"
        exec_taker = PassiveExecutor(
            freqai=mock_freqai,
            ledger=ledger,
            post_only=False,
            spread_bps=50.0,
            slippage_factor=1.0,
        )
        mock_freqai.create_order.return_value = {"status": "FILLED", "orderID": "ord-prod"}

        result = await exec_taker.execute("SOL", "BUY", 100.0, 100.0)

        assert result["status"] == "TAKER_FILLED"
        assert result["price"] == pytest.approx(100.0)
        assert exec_taker.get_metrics()["simulated_spread_usd"] == 0.0
        assert exec_taker.get_metrics()["simulated_slippage_usd"] == 0.0
        mock_freqai.create_order.assert_awaited_once_with(
            ticker="SOL",
            side="BUY",
            size=100.0,
            price=100.0,
        )


class TestMetricsAndQueue:
    def test_initial_metrics(self, executor: PassiveExecutor) -> None:
        metrics = executor.get_metrics()
        assert metrics["fill_count"] == 0
        assert metrics["reject_count"] == 0
        assert metrics["taker_fallback_count"] == 0
        assert metrics["fill_rate_pct"] == 100.0
        assert metrics["queue_depth"] == 0

    def test_fill_rate_calculation(self, executor: PassiveExecutor) -> None:
        executor._fill_count = 3
        executor._reject_count = 1
        executor._taker_fallback_count = 1
        expected = 3 / 5 * 100
        assert executor.fill_rate == pytest.approx(expected / 100.0)
        assert executor.get_metrics()["fill_rate_pct"] == pytest.approx(expected)

    def test_fill_rate_no_attempts(self, executor: PassiveExecutor) -> None:
        assert executor.fill_rate == 1.0

    def test_queue_snapshot(self, executor: PassiveExecutor) -> None:
        executor._order_queue["q-1"] = {"order_id": "ord-1", "status": "QUEUED"}
        snapshot = executor.get_queue_snapshot()
        assert len(snapshot) == 1
        assert snapshot[0]["order_id"] == "ord-1"

    def test_queue_depth(self, executor: PassiveExecutor) -> None:
        executor._order_queue["q-1"] = {"order_id": "ord-1", "status": "QUEUED"}
        assert executor.queue_depth == 1
        executor._order_queue["q-2"] = {"order_id": "ord-2", "status": "QUEUED"}
        assert executor.queue_depth == 2


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_zero_size_still_attempts(
        self, executor: PassiveExecutor, mock_freqai: AsyncMock,
    ) -> None:
        mock_freqai.post_order.return_value = {"status": "OK", "orderID": "ord-0"}
        mock_freqai.get_order_status.return_value = {
            "status": "OK",
            "order": {"remaining_size": 0, "size": 0},
        }

        result = await executor.execute("SOL", "BUY", 0.50, 0.0)

        assert result["status"] == "FILLED"

    @pytest.mark.asyncio
    async def test_post_order_raises_exception(
        self, executor: PassiveExecutor, mock_freqai: AsyncMock,
    ) -> None:
        mock_freqai.post_order.side_effect = Exception("API error")
        mock_freqai.create_order.return_value = {"status": "FILLED", "orderID": "ord-taker"}

        result = await executor.execute("SOL", "BUY", 0.50, 100.0)

        assert result["execution_path"] == "taker"

    @pytest.mark.asyncio
    async def test_queue_exception_during_await(
        self, executor: PassiveExecutor, mock_freqai: AsyncMock,
    ) -> None:
        mock_freqai.post_order.return_value = {"status": "OK", "orderID": "ord-5"}
        mock_freqai.get_order_status.side_effect = Exception("status timeout")
        mock_freqai.create_order.return_value = {"status": "FILLED", "orderID": "ord-taker"}

        result = await executor.execute("SOL", "BUY", 0.50, 100.0)

        assert result["execution_path"] == "taker"
        assert executor.taker_fallback_count == 1

    @pytest.mark.asyncio
    async def test_maker_filled_then_queue_removed(
        self, executor: PassiveExecutor, mock_freqai: AsyncMock,
    ) -> None:
        mock_freqai.post_order.return_value = {"status": "OK", "orderID": "ord-6"}
        mock_freqai.get_order_status.return_value = {
            "status": "OK",
            "order": {"remaining_size": 0, "size": 100},
        }

        await executor.execute("SOL", "BUY", 0.50, 100.0)

        assert executor.queue_depth == 0

    @pytest.mark.asyncio
    async def test_lazy_usdc_allowance_check_runs_before_buy(
        self, mock_freqai: AsyncMock, wallet_manager_mock: AsyncMock,
    ) -> None:
        executor = PassiveExecutor(
            freqai=mock_freqai,
            ledger=Mock(),
            wallet_manager=wallet_manager_mock,
            wallet_private_key="0x0000000000000000000000000000000000000000000000000000000000000001",
            usdc_spender_address="0x000000000000000000000000000000000000dEaD",
            maker_timeout_seconds=0.2,
            poll_interval=0.05,
            post_only=True,
        )
        mock_freqai.post_order.return_value = {"status": "OK", "orderID": "ord-allow"}
        mock_freqai.get_order_status.return_value = {
            "status": "OK",
            "order": {"remaining_size": 0, "size": 10},
        }

        await executor.execute("SOL", "BUY", 0.50, 10.0)

        wallet_manager_mock.ensure_usdc_allowance.assert_awaited_once()
        kwargs = wallet_manager_mock.ensure_usdc_allowance.await_args.kwargs
        assert kwargs["required_amount"] == pytest.approx(5.0)

    @pytest.mark.asyncio
    async def test_unverified_usdc_approval_does_not_log_failure(
        self, mock_freqai: AsyncMock, caplog,
    ) -> None:
        caplog.set_level("INFO")
        wallet_manager = AsyncMock()
        wallet_manager.ensure_usdc_allowance = AsyncMock(
            return_value={
                "approved": True,
                "action": "approved_unverified",
                "tx_hash": "0xtx",
                "allowance": 0.0,
                "required_amount": 5.0,
            }
        )
        executor = PassiveExecutor(
            freqai=mock_freqai,
            ledger=Mock(),
            wallet_manager=wallet_manager,
            wallet_private_key="0x0000000000000000000000000000000000000000000000000000000000000001",
            usdc_spender_address="0x000000000000000000000000000000000000dEaD",
            maker_timeout_seconds=0.2,
            poll_interval=0.05,
            post_only=True,
        )
        mock_freqai.post_order.return_value = {"status": "REJECTED", "error": "market unavailable"}

        await executor.execute("SOL", "BUY", 0.50, 10.0)

        assert "USDC allowance check failed" not in caplog.text
        assert "allowance is not yet visible via RPC" in caplog.text

    @pytest.mark.asyncio
    async def test_concurrent_orders(
        self, executor: PassiveExecutor, mock_freqai: AsyncMock,
    ) -> None:
        async def make_order(suffix: str) -> dict:
            mock_freqai.post_order.return_value = {"status": "OK", "orderID": f"ord-{suffix}"}
            mock_freqai.get_order_status.return_value = {
                "status": "OK",
                "order": {"remaining_size": 0, "size": 100},
            }
            return await executor.execute("SOL", "BUY", 0.50, 100.0)

        results = await asyncio.gather(make_order("a"), make_order("b"), make_order("c"))
        assert all(r["status"] == "FILLED" for r in results)
        assert executor.fill_count == 3

    @pytest.mark.asyncio
    async def test_taker_fallback_during_maker_error_in_await(
        self, executor: PassiveExecutor, mock_freqai: AsyncMock,
    ) -> None:
        mock_freqai.post_order.return_value = {"status": "OK", "orderID": "ord-7"}
        mock_freqai.get_order_status.side_effect = [
            {"status": "OK", "order": {"remaining_size": 100, "size": 100}},
            {"status": "OK", "order": {"remaining_size": 100, "size": 100}},
            Exception("status check crashed"),
        ]
        mock_freqai.create_order.return_value = {"status": "FILLED", "orderID": "ord-taker"}

        result = await executor.execute("SOL", "BUY", 0.50, 100.0)

        assert result["execution_path"] == "taker"


class TestStrictMakerOnly:
    @pytest.mark.asyncio
    async def test_strict_maker_only_rejects_taker_fallback_on_post_only_rejection(
        self, executor: PassiveExecutor, mock_freqai: AsyncMock,
    ) -> None:
        with patch.object(executor, "_is_strict_maker_only", return_value=True):
            mock_freqai.post_order.return_value = {
                "status": "POST_ONLY_REJECTED",
                "error": "post only would match",
            }

            result = await executor.execute("SOL", "BUY", 0.50, 100.0)

            assert result["status"] == "POST_ONLY_REJECTED"
            assert "Taker fallback denied" in result["error"]
            mock_freqai.create_order.assert_not_called()
            assert executor.reject_count == 1

    @pytest.mark.asyncio
    async def test_strict_maker_only_rejects_taker_fallback_on_timeout(
        self, executor: PassiveExecutor, mock_freqai: AsyncMock,
    ) -> None:
        with patch.object(executor, "_is_strict_maker_only", return_value=True):
            mock_freqai.post_order.return_value = {"status": "OK", "orderID": "ord-strict-timeout"}
            mock_freqai.get_order_status.return_value = {
                "status": "OK",
                "order": {"remaining_size": 100, "size": 100},
            }
            mock_freqai.cancel_order.return_value = {"status": "CANCELLED"}

            result = await executor.execute("SOL", "BUY", 0.50, 100.0)

            assert result["status"] == "CANCELLED"
            assert "Taker fallback denied" in result["error"]
            mock_freqai.create_order.assert_not_called()
            mock_freqai.cancel_order.assert_called_once_with("ord-strict-timeout")

    @pytest.mark.asyncio
    async def test_strict_maker_only_bypassed_when_override_set(
        self, executor: PassiveExecutor, mock_freqai: AsyncMock,
    ) -> None:
        mock_ledger = MagicMock()
        mock_ledger.get_safety_flags.return_value = {"strict_maker_only": True}
        executor.ledger = mock_ledger

        mock_freqai.post_order.return_value = {
            "status": "POST_ONLY_REJECTED",
            "error": "post only would match",
        }
        mock_freqai.create_order.return_value = {"status": "FILLED", "orderID": "ord-taker"}

        result = await executor.execute("SOL", "BUY", 0.50, 100.0, override_strict_maker=True)

        assert result["status"] == "TAKER_FILLED"
        assert result["execution_path"] == "taker"
        mock_freqai.create_order.assert_called_once()
