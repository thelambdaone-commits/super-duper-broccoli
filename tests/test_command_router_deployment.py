import pytest
from unittest.mock import AsyncMock, MagicMock
from telegram import Update, Message
from telegram.ext import ContextTypes
from core.command_router import LobstarCommandRouter

class MockCore:
    def __init__(self):
        self.wallet_address = "0xMockAddress123"
        self.passive_executor_allowed = True
        self._approved_until = 0.0
        self.wallet_manager = MagicMock()
        self._check_admin_auth = AsyncMock(return_value=True)

        # Setup mock layout return
        self.wallet_manager.generer_layout_telegram.return_value = ("Mock Dashboard Layout", MagicMock())
        self.wallet_manager.recuperer_soldes_on_chain = AsyncMock(return_value={
            "usdc_direct": 100.0,
            "usdc_proxy": 50.0,
            "eth_balance": 0.05
        })

    def authorize_high_value_trades(self, approver_id, ttl_seconds=900):
        self._approved_until = ttl_seconds
        return float(ttl_seconds)

@pytest.mark.asyncio
async def test_lobstar_command_router_start_routing():
    core = MockCore()
    router = LobstarCommandRouter(platform_core=core)

    # Mock Telegram Update & Message
    update = MagicMock(spec=Update)
    message = AsyncMock(spec=Message)
    message.text = "/start"
    message.chat_id = 12345
    update.message = message
    update.effective_message = message

    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)

    # Route command
    await router.route_telegram_command(update, context)

    # Assert main cockpit layout was requested and replied
    core.wallet_manager.generer_layout_telegram.assert_called_once()
    message.reply_text.assert_called_once()
    args, kwargs = message.reply_text.call_args
    assert "Mock Dashboard Layout" in kwargs.get("text", "")

@pytest.mark.asyncio
async def test_lobstar_command_router_dynamic_crypto_sentiment():
    core = MockCore()
    router = LobstarCommandRouter(platform_core=core)

    update = MagicMock(spec=Update)
    message = AsyncMock(spec=Message)
    message.text = "/sol5"
    update.message = message
    update.effective_message = message

    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)

    await router.route_telegram_command(update, context)

    message.reply_text.assert_called_once()
    args, kwargs = message.reply_text.call_args
    text = args[0] if args else kwargs.get("text", "")
    assert "🪙 ALPHA LAYER: SOL" in text

    assert "• Frame: <code>5m</code>" in text
    assert "AI Sentiment" in text

@pytest.mark.asyncio
async def test_lobstar_command_router_circuit_breakers():
    core = MockCore()
    router = LobstarCommandRouter(platform_core=core)

    update = MagicMock(spec=Update)
    message = AsyncMock(spec=Message)
    message.text = "/freeze"
    update.message = message
    update.effective_message = message

    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)

    # Freeze
    await router.route_telegram_command(update, context)
    assert core.passive_executor_allowed is False

    # Unfreeze
    message.reset_mock()
    message.text = "/unfreeze"
    await router.route_telegram_command(update, context)
    assert core.passive_executor_allowed is True


@pytest.mark.asyncio
async def test_lobstar_command_router_approve_high_value_trades():
    core = MockCore()
    router = LobstarCommandRouter(platform_core=core)

    update = MagicMock(spec=Update)
    update.effective_user = MagicMock(id=7413500821)
    message = AsyncMock(spec=Message)
    message.text = "/approve 5"
    update.message = message
    update.effective_message = message

    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.args = ["5"]

    await router.route_telegram_command(update, context)

    core._check_admin_auth.assert_awaited_once()
    assert core._approved_until == 300
    message.reply_text.assert_called_once()


@pytest.mark.asyncio
async def test_lobstar_command_router_launch_btc5up(monkeypatch):
    core = MockCore()
    router = LobstarCommandRouter(platform_core=core)

    class _Service:
        def launch(self, timeframe: str, direction: str):
            class _Result:
                interval = timeframe
                requested_direction = direction
                strongest_direction = "up"
                strongest_probability = 0.73
                prob_up = 0.73
                prob_down = 0.27
                best_variant = "balanced"
                best_val_accuracy = 0.66
                train_samples = 180
                val_samples = 45
            return _Result()

    core.btc_launch_service = _Service()

    update = MagicMock(spec=Update)
    message = AsyncMock(spec=Message)
    message.text = "/launchbtc5up"
    update.message = message
    update.effective_message = message

    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)

    await router.route_telegram_command(update, context)

    message.reply_text.assert_called_once()
    args, kwargs = message.reply_text.call_args
    text = args[0] if args else kwargs.get("text", "")
    assert "BTC LAUNCH 5M" in text
    assert "73.00%" in text
    assert "UP" in text
