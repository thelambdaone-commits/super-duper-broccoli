from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from core.wallet_manager import PolymarketWalletManager


@pytest.mark.asyncio
async def test_ensure_usdc_allowance_retries_after_receipt_until_allowance_visible() -> None:
    manager = PolymarketWalletManager(vault_handler=None, polygon_rpc_url="https://polygon.example")
    manager.approve_usdc = AsyncMock(return_value="0xtx")
    manager.get_erc20_allowance = AsyncMock(side_effect=[0.0, 0.0, 12.0])

    fake_w3 = Mock()
    fake_w3.eth.wait_for_transaction_receipt.return_value = SimpleNamespace(status=1)

    with patch("web3.Web3", return_value=fake_w3):
        result = await manager.ensure_usdc_allowance(
            private_key="0x" + "1" * 64,
            spender_address="0x000000000000000000000000000000000000dEaD",
            required_amount=5.0,
            owner_address="0x000000000000000000000000000000000000bEEF",
            post_receipt_retry_count=3,
            post_receipt_retry_delay_seconds=0.0,
        )

    assert result["approved"] is True
    assert result["action"] == "approved"
    assert result["allowance"] == 12.0


@pytest.mark.asyncio
async def test_ensure_usdc_allowance_marks_success_as_unverified_when_rpc_never_updates() -> None:
    manager = PolymarketWalletManager(vault_handler=None, polygon_rpc_url="https://polygon.example")
    manager.approve_usdc = AsyncMock(return_value="0xtx")
    manager.get_erc20_allowance = AsyncMock(side_effect=[0.0, 0.0, 0.0])

    fake_w3 = Mock()
    fake_w3.eth.wait_for_transaction_receipt.return_value = SimpleNamespace(status=1)

    with patch("web3.Web3", return_value=fake_w3):
        result = await manager.ensure_usdc_allowance(
            private_key="0x" + "1" * 64,
            spender_address="0x000000000000000000000000000000000000dEaD",
            required_amount=5.0,
            owner_address="0x000000000000000000000000000000000000bEEF",
            post_receipt_retry_count=2,
            post_receipt_retry_delay_seconds=0.0,
        )

    assert result["approved"] is True
    assert result["action"] == "approved_unverified"
