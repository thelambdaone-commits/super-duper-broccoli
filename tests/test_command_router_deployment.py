import pytest
from unittest.mock import AsyncMock, MagicMock
from telegram import Update, Message
from telegram.ext import ContextTypes
from core.command_router import LobstarCommandRouter

class MockCore:
    def __init__(self):
        self.wallet_address = "0xMockAddress123"
        self.passive_executor_allowed = True
        self.wallet_manager = MagicMock()

        # Setup mock layout return
        self.wallet_manager.generer_layout_telegram.return_value = ("Mock Dashboard Layout", MagicMock())
        self.wallet_manager.recuperer_soldes_on_chain = AsyncMock(return_value={
            "usdc_direct": 100.0,
            "usdc_proxy": 50.0,
            "eth_balance": 0.05
        })

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
    assert "🪙 LOBSTAR INTELLIGENCE LAYER: SOL" in text
    assert "5m Rolling Frame" in text
    assert "AI Sentiment Vector" in text

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
