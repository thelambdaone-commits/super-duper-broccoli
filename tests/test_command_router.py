import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
import pytest
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from telegram_scraper.command_router import CommandRouter
from utils.polymarket_client import Market


def make_market(slug: str, question: str, yes: float, no: float, volume: float = 10_000) -> Market:
    return Market(
        condition_id=f"cond-{slug}",
        slug=slug,
        question=question,
        description="",
        outcomes=["Yes", "No"],
        outcome_prices=[yes, no],
        tokens=[
            {"outcome": "Yes", "token_id": f"{slug}-yes"},
            {"outcome": "No", "token_id": f"{slug}-no"},
        ],
        active=True,
        closed=False,
        volume=volume,
        liquidity=5_000,
    )


class FakeClient:
    def __init__(self, markets=None):
        self.markets = markets or []

    def search_markets(self, query, limit=40):
        return self.markets

    def list_markets(self, limit=150, sort_by="volume"):
        return self.markets


@pytest.mark.asyncio
async def test_cmd_crypto_horizon_btc5_success() -> None:
    # Set up mocks
    listener = MagicMock()
    listener._check_auth = AsyncMock(return_value=True)
    listener.reply_to = AsyncMock()
    listener.application = MagicMock()

    # Mock the horizon analyzer client
    mock_market = make_market("btc-updown-5m", "BTC up or down 5m?", 0.65, 0.35)
    mock_market.end_date = "2026-05-17T12:00:00Z"

    listener._scanner = MagicMock()
    listener._scanner.client = FakeClient([mock_market])

    router = CommandRouter(listener)

    # Mock Telegram Update & Message
    message = MagicMock()
    message.text = "/btc5"
    message.chat_id = 123
    update = MagicMock()
    update.effective_message = message

    # Execute
    await router._cmd_crypto_horizon(update, None)

    # Verify auth was checked
    listener._check_auth.assert_called_once_with(update)

    # Verify a reply was sent
    listener.reply_to.assert_called_once()
    reply_args = listener.reply_to.call_args
    text = reply_args[0][0]
    reply_markup = reply_args[1].get("reply_markup")
    parse_mode = reply_args[1].get("parse_mode")

    # Assert correct horizon is parsed and formatted
    assert "LOBSTAR CRYPTO SENTIMENT — BTC (5)" in text
    assert reply_markup is not None
    assert parse_mode == ParseMode.MARKDOWN


@pytest.mark.asyncio
async def test_cmd_crypto_horizon_all_valid_command_variations() -> None:
    listener = MagicMock()
    listener._check_auth = AsyncMock(return_value=True)
    listener.reply_to = AsyncMock()
    listener.application = MagicMock()

    # Mock the horizon analyzer client with some markets
    listener._scanner = MagicMock()
    listener._scanner.client = FakeClient([make_market("btc-updown-15m", "BTC up or down 15m?", 0.70, 0.30)])

    router = CommandRouter(listener)

    # Test distinct quick horizon commands
    quick_commands = ["/btc15", "/btc1h", "/eth5", "/sol15", "/xrp1h", "/hype5", "/doge5", "/bnb1h"]

    for cmd in quick_commands:
        listener.reply_to.reset_mock()
        message = MagicMock()
        message.text = cmd
        message.chat_id = 123
        update = MagicMock()
        update.effective_message = message

        await router._cmd_crypto_horizon(update, None)

        listener.reply_to.assert_called_once()
        text = listener.reply_to.call_args[0][0]
        assert "LOBSTAR CRYPTO SENTIMENT" in text


@pytest.mark.asyncio
async def test_cmd_crypto_markets_btc_success() -> None:
    listener = MagicMock()
    listener._check_auth = AsyncMock(return_value=True)
    listener.reply_to = AsyncMock()
    listener.application = MagicMock()

    # Setup fake Polymarket client returning active markets matching classifier
    mock_market = make_market("bitcoin-weekly-price", "Will Bitcoin reach $100k?", 0.85, 0.15)
    listener._scanner = MagicMock()
    listener._scanner.client = FakeClient([mock_market])

    router = CommandRouter(listener)

    # Mock /btc command
    message = MagicMock()
    message.text = "/btc"
    message.chat_id = 123
    update = MagicMock()
    update.effective_message = message

    # Mock classifier to classify asset as BTC
    with patch("utils.crypto_market_intelligence.CryptoMarketIntelligence._classify_asset", return_value="BTC"):
        await router._cmd_crypto_markets(update, None)

    # Verify a reply listing markets was sent
    listener.reply_to.assert_called_once()
    text = listener.reply_to.call_args[0][0]
    assert "MARCHÉS ACTIFS POUR BTC" in text
    assert "Will Bitcoin reach $100k?" in text
    assert "Slug: `bitcoin-weekly-price`" in text


@pytest.mark.asyncio
async def test_cmd_crypto_markets_all_assets() -> None:
    listener = MagicMock()
    listener._check_auth = AsyncMock(return_value=True)
    listener.reply_to = AsyncMock()
    listener.application = MagicMock()
    listener._scanner = MagicMock()

    router = CommandRouter(listener)

    # Test all base asset quick commands
    for asset in ["btc", "eth", "sol", "xrp", "hype", "doge", "bnb"]:
        listener.reply_to.reset_mock()
        message = MagicMock()
        message.text = f"/{asset}"
        message.chat_id = 123
        update = MagicMock()
        update.effective_message = message

        # Mock the client return and classification matching current asset
        mock_market = make_market(f"{asset}-market", f"Will {asset.upper()} double?", 0.50, 0.50)
        listener._scanner.client = FakeClient([mock_market])

        with patch("utils.crypto_market_intelligence.CryptoMarketIntelligence._classify_asset", return_value=asset.upper()):
            await router._cmd_crypto_markets(update, None)

        listener.reply_to.assert_called_once()
        text = listener.reply_to.call_args[0][0]
        assert f"MARCHÉS ACTIFS POUR {asset.upper()}" in text
        assert f"Will {asset.upper()} double?" in text


@pytest.mark.asyncio
async def test_cmd_manual_dynamic_lookup() -> None:
    listener = MagicMock()
    listener.reply_to = AsyncMock()
    listener.application = MagicMock()
    listener.access_control = MagicMock()
    listener.access_control.est_admin = MagicMock(return_value=True)

    router = CommandRouter(listener)

    # 1. Test /man with arguments (e.g. "wallet")
    message_wallet = MagicMock()
    message_wallet.text = "/man wallet"
    message_wallet.chat_id = 123
    update_wallet = MagicMock()
    update_wallet.effective_message = message_wallet
    update_wallet.effective_chat = MagicMock()
    update_wallet.effective_chat.id = 123

    context_wallet = MagicMock()
    context_wallet.args = ["wallet"]

    await router._cmd_manual(update_wallet, context_wallet)
    listener.reply_to.assert_called_once()
    text_wallet = listener.reply_to.call_args[0][0]
    assert "MANUEL LOBSTAR — /wallet" in text_wallet
    assert "Gérer les portefeuilles, soldes" in text_wallet

    # 2. Test /man with dynamic horizon (e.g. "btc5")
    listener.reply_to.reset_mock()
    context_btc5 = MagicMock()
    context_btc5.args = ["btc5"]

    await router._cmd_manual(update_wallet, context_btc5)
    listener.reply_to.assert_called_once()
    text_btc5 = listener.reply_to.call_args[0][0]
    assert "MANUEL LOBSTAR — /btc5" in text_btc5
    assert "Sentiment du marché crypto pour BTC sur l'horizon 5." in text_btc5

    # 3. Test /man with unknown command
    listener.reply_to.reset_mock()
    context_unknown = MagicMock()
    context_unknown.args = ["unknown_cmd"]

    await router._cmd_manual(update_wallet, context_unknown)
    listener.reply_to.assert_called_once()
    text_unknown = listener.reply_to.call_args[0][0]
    assert "Commande `/unknown_cmd` introuvable." in text_unknown

    # 4. Test /man with no arguments (fallback to HelpManager menu)
    listener.reply_to.reset_mock()
    context_none = MagicMock()
    context_none.args = []

    with patch("utils.help_manager.HelpManager.send_menu", new_callable=AsyncMock) as mock_send_menu:
        await router._cmd_manual(update_wallet, context_none)
        mock_send_menu.assert_called_once()


@pytest.mark.asyncio
async def test_cmd_gsd_success() -> None:
    listener = MagicMock()
    listener._check_admin_auth = AsyncMock(return_value=True)

    status_msg = AsyncMock()
    listener.reply_to = AsyncMock(return_value=status_msg)

    router = CommandRouter(listener)

    message = MagicMock()
    message.text = "/gsd --dry-run timing delay in binance websocket client"
    update = MagicMock()
    update.effective_message = message

    context = MagicMock()
    context.args = ["--dry-run", "timing", "delay", "in", "binance", "websocket", "client"]

    await router._cmd_gsd(update, context)

    listener.reply_to.assert_called_once()
    status_msg.edit_text.assert_called_once()
    final_text = status_msg.edit_text.call_args[0][0]
    assert "GSD RESOLUTION PROCESS COMPLETE" in final_text
    assert "RESOLVED & VERIFIED" in final_text
