from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from interface.command_router import CommandRouter


@pytest.mark.asyncio
async def test_crypto_menu_horizon_buttons_cover_each_asset() -> None:
    listener = SimpleNamespace(
        application=MagicMock(),
        reply_to=AsyncMock(),
        _check_auth=AsyncMock(return_value=True),
    )
    router = CommandRouter(listener)
    update = MagicMock()
    context = SimpleNamespace(args=[])

    await router._cmd_crypto(update, context)

    _, kwargs = listener.reply_to.await_args
    markup = kwargs["reply_markup"]
    callback_data = [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
    ]

    assert "crypto_horizon:btc:5" in callback_data
    assert "crypto_horizon:eth:1h" in callback_data
    assert "crypto_horizon:sol:4h" in callback_data
    assert "crypto_horizon:xrp:1d" in callback_data
    assert "crypto_horizon:bnb:15" in callback_data
    assert "btc_launch:5m" in callback_data
    assert "btc_launch:15m" in callback_data


@pytest.mark.asyncio
async def test_btc5_routes_to_btc_launch_buttons() -> None:
    listener = SimpleNamespace(
        application=MagicMock(),
        reply_to=AsyncMock(),
        _check_auth=AsyncMock(return_value=True),
    )
    router = CommandRouter(listener)
    router.render_btc_launch = AsyncMock(
        return_value=("BTC 5M READY", MagicMock(inline_keyboard=[[SimpleNamespace(callback_data="btc_paper:5m:up")]]))
    )
    update = MagicMock()
    update.effective_message = SimpleNamespace(text="/btc5")
    context = SimpleNamespace(args=[])

    await router._cmd_crypto_horizon(update, context)

    router.render_btc_launch.assert_awaited_once_with("5m")
    listener.reply_to.assert_awaited_once()


@pytest.mark.asyncio
async def test_render_btc_launch_supports_mocked_service_without_thread_handoff() -> None:
    listener = SimpleNamespace(
        application=MagicMock(),
        reply_to=AsyncMock(),
        _check_auth=AsyncMock(return_value=True),
    )
    router = CommandRouter(listener)
    listener._btc_launch_service = SimpleNamespace(
        get_or_launch=Mock(
            return_value=SimpleNamespace(
                interval="5m",
                requested_direction="up",
                strongest_direction="up",
                strongest_probability=0.72,
                prob_up=0.72,
                prob_down=0.28,
                best_variant="mocked",
                best_val_accuracy=0.61,
                train_samples=100,
                val_samples=20,
                generated_at=0.0,
            )
        )
    )

    text, markup = await router.render_btc_launch("5m")

    listener._btc_launch_service.get_or_launch.assert_called_once_with("5m", "up", False)
    assert "BTC 5M" in text
    assert markup is not None
