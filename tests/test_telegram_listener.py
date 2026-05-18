import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from telegram_scraper.telegram_listener import (
    TELEGRAM_SAFE_MESSAGE_LENGTH,
    TelegramListener,
    _safe_signal_for_log,
    split_telegram_message,
)


class FakeCopyAgent:
    def __init__(self) -> None:
        self.is_running = False
        self.started = False
        self.stopped = False
        self.config = SimpleNamespace(
            copy_multiplier=0.1,
            max_copy_notional=100.0,
            min_copy_notional=1.0,
            buy_only=True,
            slippage_tolerance=0.02,
        )

    def get_stats(self) -> dict:
        return {
            "target_wallet": "0x1111111111111111111111111111111111111111",
            "multiplier": 0.1,
            "buy_only_mode": True,
            "trades_copied": 0,
            "session_notional": 0.0,
        }

    async def start_monitoring(self, poll_interval=10.0, on_new_trade=None) -> None:
        self.started = True
        self.is_running = True

    def stop_monitoring(self) -> None:
        self.stopped = True
        self.is_running = False

    def update_config(self, config) -> None:
        self.config = config


@pytest.mark.asyncio
async def test_send_message_returns_false_before_start() -> None:
    listener = TelegramListener(bot_token="token", on_signal=lambda _: None, chat_id=123)

    assert await listener.send_message("hello") is False


@pytest.mark.asyncio
async def test_send_message_uses_configured_chat_id() -> None:
    listener = TelegramListener(bot_token="token", on_signal=lambda _: None, chat_id=123)
    listener.application = SimpleNamespace(
        bot=SimpleNamespace(send_message=AsyncMock())
    )

    assert await listener.send_message("hello") is True
    listener.application.bot.send_message.assert_awaited_once_with(
        chat_id=123,
        text="hello",
    )


@pytest.mark.asyncio
async def test_send_message_accepts_explicit_parse_mode() -> None:
    listener = TelegramListener(bot_token="token", on_signal=lambda _: None, chat_id=123)
    listener.application = SimpleNamespace(
        bot=SimpleNamespace(send_message=AsyncMock())
    )

    assert await listener.send_message("<b>hello</b>", parse_mode="HTML") is True
    listener.application.bot.send_message.assert_awaited_once_with(
        chat_id=123,
        text="<b>hello</b>",
        parse_mode="HTML",
    )


@pytest.mark.asyncio
async def test_send_message_splits_long_text() -> None:
    listener = TelegramListener(bot_token="token", on_signal=lambda _: None, chat_id=123)
    listener.application = SimpleNamespace(
        bot=SimpleNamespace(send_message=AsyncMock())
    )
    text = "a" * (TELEGRAM_SAFE_MESSAGE_LENGTH + 20)

    assert await listener.send_message(text) is True
    assert listener.application.bot.send_message.await_count == 2
    for call in listener.application.bot.send_message.await_args_list:
        assert len(call.kwargs["text"]) <= TELEGRAM_SAFE_MESSAGE_LENGTH


@pytest.mark.asyncio
async def test_reply_to_message_update() -> None:
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(message=message, channel_post=None)
    listener = TelegramListener(bot_token="token", on_signal=lambda _: None)

    assert await listener.reply_to("ok", update) is True
    message.reply_text.assert_awaited_once_with("ok", parse_mode="Markdown")


@pytest.mark.asyncio
async def test_reply_to_accepts_explicit_parse_mode() -> None:
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(message=message, channel_post=None)
    listener = TelegramListener(bot_token="token", on_signal=lambda _: None)

    assert await listener.reply_to("<b>ok</b>", update, parse_mode="HTML") is True
    message.reply_text.assert_awaited_once_with("<b>ok</b>", parse_mode="HTML")


@pytest.mark.asyncio
async def test_reply_to_channel_post_update() -> None:
    channel_post = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(message=None, channel_post=channel_post)
    listener = TelegramListener(bot_token="token", on_signal=lambda _: None)

    assert await listener.reply_to("ok", update) is True
    channel_post.reply_text.assert_awaited_once_with("ok", parse_mode="Markdown")


def test_safe_signal_for_log_drops_update_object() -> None:
    signal = {"asset": "SOL", "price": 0.5, "update": object()}

    assert _safe_signal_for_log(signal) == {"asset": "SOL", "price": 0.5}


def test_split_telegram_message_prefers_line_boundaries() -> None:
    chunks = split_telegram_message("line1\nline2\nline3", limit=12)

    assert chunks == ["line1\nline2", "line3"]


@pytest.mark.asyncio
async def test_private_message_signal_is_forwarded_when_authorized() -> None:
    received = []
    message = SimpleNamespace(
        text="BUY SOL @ 0.50",
        message_id=44,
        chat_id=777,
        chat=SimpleNamespace(type="private"),
        reply_text=AsyncMock(),
    )
    update = SimpleNamespace(message=message, channel_post=None)
    listener = TelegramListener(
        bot_token="token",
        on_signal=received.append,
        private_chat_ids={777},
    )

    await listener._handle_private_message(update, None)

    assert len(received) == 1
    assert received[0]["asset"] == "SOL"
    assert received[0]["chat_id"] == 777
    message.reply_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_private_message_replies_help_when_no_signal() -> None:
    message = SimpleNamespace(
        text="hello",
        message_id=45,
        chat_id=777,
        chat=SimpleNamespace(type="private"),
        reply_text=AsyncMock(),
    )
    update = SimpleNamespace(message=message, channel_post=None)
    listener = TelegramListener(
        bot_token="token",
        on_signal=lambda _: None,
        private_chat_ids={777},
    )

    await listener._handle_private_message(update, None)

    message.reply_text.assert_awaited_once()
    assert "/help" in message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_private_message_rejects_unauthorized_chat() -> None:
    message = SimpleNamespace(
        text="BUY SOL @ 0.50",
        message_id=46,
        chat_id=888,
        chat=SimpleNamespace(type="private"),
        reply_text=AsyncMock(),
    )
    update = SimpleNamespace(message=message, channel_post=None)
    listener = TelegramListener(
        bot_token="token",
        on_signal=lambda _: None,
        private_chat_ids={777},
    )

    await listener._handle_private_message(update, None)

    message.reply_text.assert_awaited_once_with("Private chat is not authorized for this bot.", parse_mode="Markdown")


@pytest.mark.asyncio
async def test_check_auth_accepts_configured_chat_id() -> None:
    message = SimpleNamespace(
        chat_id=-100,
        chat=SimpleNamespace(type="channel"),
        reply_text=AsyncMock(),
    )
    update = SimpleNamespace(message=None, channel_post=message)
    listener = TelegramListener(bot_token="token", on_signal=lambda _: None, chat_id=-100)

    assert await listener._check_auth(update) is True
    message.reply_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_check_auth_rejects_unknown_chat() -> None:
    message = SimpleNamespace(
        chat_id=-200,
        chat=SimpleNamespace(type="group"),
        reply_text=AsyncMock(),
    )
    update = SimpleNamespace(message=message, channel_post=None)
    listener = TelegramListener(bot_token="token", on_signal=lambda _: None, chat_id=-100)

    assert await listener._check_auth(update) is False
    message.reply_text.assert_awaited_once_with("Unauthorized.", parse_mode="Markdown")


@pytest.mark.asyncio
async def test_check_auth_accepts_access_control_admin_when_chat_id_is_channel() -> None:
    from utils.access_control import AccessControlManager

    message = SimpleNamespace(
        chat_id=123,
        chat=SimpleNamespace(type="private"),
        reply_text=AsyncMock(),
    )
    update = SimpleNamespace(
        message=message,
        channel_post=None,
        effective_user=SimpleNamespace(id=123),
    )
    listener = TelegramListener(
        bot_token="token",
        on_signal=lambda _: None,
        chat_id=-100,
        access_control=AccessControlManager(admin_chat_ids=[123]),
    )

    assert await listener._check_auth(update) is True
    message.reply_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_error_replies_to_command_update() -> None:
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(message=message, channel_post=None)
    context = SimpleNamespace(error=RuntimeError("boom"))
    listener = TelegramListener(bot_token="token", on_signal=lambda _: None)

    await listener._handle_error(update, context)

    message.reply_text.assert_awaited_once()
    assert "Erreur interne" in message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_cmd_check_reports_statuses() -> None:
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(message=message, channel_post=None)
    listener = TelegramListener(bot_token="12345678:token", on_signal=lambda _: None)

    # Mock httpx.AsyncClient
    mock_response = SimpleNamespace(status_code=200)
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_client.aclose = AsyncMock()

    with patch("httpx.AsyncClient", return_value=mock_client):
        with patch.dict(os.environ, {"VAULT_TOKEN": "vtoken", "WS_URL": "ws://test"}):
            await listener._cmd_check(update, None)

    message.reply_text.assert_awaited_once()
    text = message.reply_text.call_args[0][0]
    assert "*API Connectivity Check*" in text
    assert "*Telegram:* token=12345678..." in text
    assert "*Vault:* OK" in text
    assert "*Polymarket CLOB:* OK" in text
    assert "*WebSocket:* CONFIGURED" in text


@pytest.mark.asyncio
async def test_cmd_copy_start_starts_monitoring() -> None:
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(message=message, channel_post=None)
    context = SimpleNamespace(args=["start"])
    copy_agent = FakeCopyAgent()
    listener = TelegramListener(bot_token="token", on_signal=lambda _: None)
    listener.attach_components(copy_agent=copy_agent)

    await listener._cmd_copy(update, context)
    await asyncio.sleep(0)

    assert copy_agent.started is True
    message.reply_text.assert_awaited_once_with("✅ Copy trading started", parse_mode="Markdown")


@pytest.mark.asyncio
async def test_cmd_copy_stop_stops_monitoring() -> None:
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(message=message, channel_post=None)
    context = SimpleNamespace(args=["stop"])
    copy_agent = FakeCopyAgent()
    copy_agent.is_running = True
    listener = TelegramListener(bot_token="token", on_signal=lambda _: None)
    listener.attach_components(copy_agent=copy_agent)

    await listener._cmd_copy(update, context)

    assert copy_agent.stopped is True
    message.reply_text.assert_awaited_once_with("🛑 Copy trading stopped", parse_mode="Markdown")


@pytest.mark.asyncio
async def test_callback_without_scanner_replies_instead_of_crashing() -> None:
    reply_text = AsyncMock()
    query = SimpleNamespace(
        message=SimpleNamespace(chat_id=123, reply_text=reply_text),
        data="scan",
        answer=AsyncMock(),
    )
    update = SimpleNamespace(callback_query=query, message=None, channel_post=None)
    listener = TelegramListener(bot_token="token", on_signal=lambda _: None, admin_chat_ids={123})

    await listener._handle_callback(update, None)

    query.answer.assert_awaited_once_with()
    reply_text.assert_awaited_once_with("Scanner not available.")


@pytest.mark.asyncio
async def test_callback_without_ledger_replies_instead_of_crashing() -> None:
    reply_text = AsyncMock()
    query = SimpleNamespace(
        message=SimpleNamespace(chat_id=123, reply_text=reply_text),
        data="wallet",
        answer=AsyncMock(),
    )
    update = SimpleNamespace(callback_query=query, message=None, channel_post=None)
    listener = TelegramListener(bot_token="token", on_signal=lambda _: None, admin_chat_ids={123})
    listener._cmd_wallet_cockpit = AsyncMock()

    await listener._handle_callback(update, None)

    query.answer.assert_awaited_once_with()
    listener._cmd_wallet_cockpit.assert_awaited_once_with(update, None)


@pytest.mark.asyncio
async def test_cmd_wallets_renders_inline_keyboard() -> None:
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(message=message, channel_post=None)
    listener = TelegramListener(bot_token="12345678:token", on_signal=lambda _: None)

    # Mock the authorization helper to always return True
    listener._is_authorized_private_message = lambda _: True

    # Setup mocked credential manager responses
    mock_wallets = [
        {"address": "0x1111111111111111111111111111111111111111", "private_key": "0xabc"},
        {"address": "0x2222222222222222222222222222222222222222", "private_key": "0xdef"}
    ]
    
    mock_account = SimpleNamespace(address="0x1111111111111111111111111111111111111111")
    with patch("utils.credential_manager.CredentialManager.list_wallets", return_value=mock_wallets):
        with patch("utils.credential_manager.CredentialManager.get_or_generate_private_key", return_value="0xmock"):
            with patch("eth_account.Account.from_key", return_value=mock_account):
                await listener._cmd_wallets(update, None)

    message.reply_text.assert_awaited_once()
    text = message.reply_text.call_args[0][0]
    reply_markup = message.reply_text.call_args[1]["reply_markup"]

    assert "🦞 *LOBSTAR WALLET MANAGER*" in text
    assert "0x1111111111111111111111111111111111111111" in text
    assert "0x2222222222222222222222222222222222222222" in text
    
    # Check buttons
    buttons = reply_markup.inline_keyboard
    assert len(buttons) == 2
    assert buttons[0][0].text == "🟢 0x1111...1111"
    assert buttons[0][0].callback_data == "wallet_select:0x1111111111111111111111111111111111111111"
    assert buttons[1][0].text == "Select 0x2222...2222"
    assert buttons[1][0].callback_data == "wallet_select:0x2222222222222222222222222222222222222222"


@pytest.mark.asyncio
async def test_cmd_start_renders_steering_console() -> None:
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(message=message, channel_post=None)
    listener = TelegramListener(bot_token="12345678:token", on_signal=lambda _: None)

    listener._is_authorized_private_message = lambda _: True
    listener._get_mode = lambda: "PAPER"

    mock_account = SimpleNamespace(address="0x1111111111111111111111111111111111111111")
    with patch("utils.credential_manager.CredentialManager.get_or_generate_private_key", return_value="0xmock"):
        with patch("eth_account.Account.from_key", return_value=mock_account):
            await listener._cmd_start(update, None)

    message.reply_text.assert_awaited_once()
    text = message.reply_text.call_args[0][0]
    reply_markup = message.reply_text.call_args[1]["reply_markup"]

    assert "🦞 *LOBSTAR QUANT CONTROL PANEL*" in text
    assert "0x1111111111111111111111111111111111111111" in text
    assert "PAPER" in text

    buttons = reply_markup.inline_keyboard
    assert len(buttons) == 4
    assert buttons[0][0].text == "📡 Status"
    assert buttons[0][0].callback_data == "start_status"
    assert buttons[0][1].text == "⚡ Scan Markets"
    assert buttons[0][1].callback_data == "scan"
    assert buttons[1][0].text == "💳 Balance"
    assert buttons[1][0].callback_data == "balance"
    assert buttons[1][1].text == "💼 Positions"
    assert buttons[1][1].callback_data == "start_positions"


@pytest.mark.asyncio
async def test_cmd_crypto_markets_searches_polymarket() -> None:
    from telegram_scraper.command_router import CommandRouter
    from utils.polymarket_client import Market
    
    message = SimpleNamespace(text="/btc")
    update = SimpleNamespace(message=message, effective_message=message, channel_post=None)
    
    listener = TelegramListener(bot_token="12345678:token", on_signal=lambda _: None)
    listener.reply_to = AsyncMock()
    listener._check_auth = AsyncMock(return_value=True)
    
    router = CommandRouter(listener)
    
    fake_market = Market(
        condition_id="0x123",
        slug="btc-above-66k-may-17",
        question="Will Bitcoin be above 66k on May 17?",
        description="Description",
        outcomes=["YES", "NO"],
        outcome_prices=[0.65, 0.35],
        tokens=[{"outcome": "yes", "token_id": "yes123"}, {"outcome": "no", "token_id": "no123"}],
        active=True,
        closed=False,
        volume=100000.0,
        liquidity=5000.0
    )
    
    with patch("utils.polymarket_client.PolymarketClient.search_markets", return_value=[fake_market]) as mock_search:
        await router._cmd_crypto_markets(update, None)
        mock_search.assert_called_once_with("Bitcoin", limit=40)
        
    listener.reply_to.assert_called_once()
    reply_text = listener.reply_to.call_args[0][0]
    
    assert "MARCHÉS ACTIFS POUR BTC" in reply_text
    assert "Will Bitcoin be above 66k on May 17?" in reply_text
    assert "btc-above-66k-may-17" in reply_text
    assert "65%" in reply_text


@pytest.mark.asyncio
async def test_cmd_all_crypto_markets_lists_top_crypto() -> None:
    from telegram_scraper.command_router import CommandRouter
    from utils.polymarket_client import Market
    
    message = SimpleNamespace(text="/crypto")
    update = SimpleNamespace(message=message, effective_message=message, channel_post=None)
    
    listener = TelegramListener(bot_token="12345678:token", on_signal=lambda _: None)
    listener.reply_to = AsyncMock()
    listener._check_auth = AsyncMock(return_value=True)
    
    router = CommandRouter(listener)
    
    fake_market = Market(
        condition_id="0x123",
        slug="btc-above-66k-may-17",
        question="Will Bitcoin be above 66k on May 17?",
        description="Description",
        outcomes=["YES", "NO"],
        outcome_prices=[0.65, 0.35],
        tokens=[{"outcome": "yes", "token_id": "yes123"}, {"outcome": "no", "token_id": "no123"}],
        active=True,
        closed=False,
        volume=100000.0,
        liquidity=5000.0
    )
    
    with patch("utils.polymarket_client.PolymarketClient.list_markets", return_value=[fake_market]) as mock_list:
        await router._cmd_all_crypto_markets(update, None)
        mock_list.assert_called_once_with(limit=100, sort_by="volume")
        
    listener.reply_to.assert_called_once()
    reply_text = listener.reply_to.call_args[0][0]
    
    assert "TOUS LES MARCHÉS CRYPTO ACTIFS" in reply_text
    assert "[BTC]" in reply_text
    assert "Will Bitcoin be above 66k on May 17?" in reply_text
    assert "btc-above-66k-may-17" in reply_text


@pytest.mark.asyncio
async def test_cmd_updown_lists_short_term_price_bets() -> None:
    from telegram_scraper.command_router import CommandRouter
    from utils.polymarket_client import Market
    
    # Test /updown btc
    message = SimpleNamespace(text="/updown btc")
    update = SimpleNamespace(message=message, effective_message=message, channel_post=None)
    context = SimpleNamespace(args=["btc"])
    
    listener = TelegramListener(bot_token="12345678:token", on_signal=lambda _: None)
    listener.reply_to = AsyncMock()
    listener._check_auth = AsyncMock(return_value=True)
    
    router = CommandRouter(listener)
    
    fake_market = Market(
        condition_id="0x123",
        slug="btc-above-66k-may-17",
        question="Will Bitcoin be above 66k on May 17?",
        description="Description",
        outcomes=["YES", "NO"],
        outcome_prices=[0.65, 0.35],
        tokens=[{"outcome": "yes", "token_id": "yes123"}, {"outcome": "no", "token_id": "no123"}],
        active=True,
        closed=False,
        volume=100000.0,
        liquidity=5000.0
    )
    
    with patch("utils.polymarket_client.PolymarketClient.list_markets", return_value=[fake_market]) as mock_list:
        with patch("utils.polymarket_client.PolymarketClient.search_markets", return_value=[]) as mock_search:
            await router._cmd_updown(update, context)
            mock_list.assert_called_once_with(limit=250, sort_by="volume")
            # Should have called search for 9 exhaustive crypto target terms
            assert mock_search.call_count == 9
            
    listener.reply_to.assert_called_once()
    reply_text = listener.reply_to.call_args[0][0]
    
    assert "MARCHÉS CRYPTO UPDOWN ACTIFS" in reply_text
    assert "[BTC]" in reply_text
    assert "Will Bitcoin be above 66k on May 17?" in reply_text
    assert "btc-above-66k-may-17" in reply_text


@pytest.mark.asyncio
async def test_cmd_ai_status_errors_and_prompt(monkeypatch):
    # Mock environment and vault to ensure no live OpenRouter key is resolved during testing
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    from utils.vault_handler import VaultHandler
    monkeypatch.setattr(VaultHandler, "fetch_quantum_secrets", lambda self: {})

    from telegram_scraper.command_router import CommandRouter
    # Setup TelegramListener and CommandRouter mocks
    listener = TelegramListener(bot_token="12345678:token", on_signal=lambda _: None)
    listener.reply_to = AsyncMock()
    listener._check_admin_auth = AsyncMock(return_value=True)
    router = CommandRouter(listener)

    # 1. Test status routing
    message_status = SimpleNamespace(text="/ai status")
    update_status = SimpleNamespace(message=message_status, effective_message=message_status, channel_post=None)
    context_status = SimpleNamespace(args=["status"])

    await router._cmd_ai(update_status, context_status)
    assert listener.reply_to.call_count == 1
    reply_text = listener.reply_to.call_args[0][0]
    assert "AI Agents Status" in reply_text

    listener.reply_to.reset_mock()

    # 2. Test errors routing
    message_errors = SimpleNamespace(text="/ai errors")
    update_errors = SimpleNamespace(message=message_errors, effective_message=message_errors, channel_post=None)
    context_errors = SimpleNamespace(args=["errors"])

    await router._cmd_ai(update_errors, context_errors)
    assert listener.reply_to.call_count == 1
    reply_text = listener.reply_to.call_args[0][0]
    # Could be log contents or failing to read logs, both are correct behaviors
    assert "Latest AI/System Errors" in reply_text or "Failed to read logs" in reply_text

    listener.reply_to.reset_mock()

    # 3. Test custom prompt routing
    message_prompt = SimpleNamespace(text="/ai Will bitcoin hit $100k?")
    update_prompt = SimpleNamespace(message=message_prompt, effective_message=message_prompt, channel_post=None)
    context_prompt = SimpleNamespace(args=["Will", "bitcoin", "hit", "$100k?"])

    # Mock the edit_text of the returned status message
    mock_status_msg = AsyncMock()
    listener.reply_to.return_value = mock_status_msg

    await router._cmd_ai(update_prompt, context_prompt)
    
    # Assert initial status reply was sent
    assert listener.reply_to.call_count == 1
    initial_text = listener.reply_to.call_args[0][0]
    assert "Lobstar AI Council is reflecting" in initial_text

    # Assert edit_text was called with final (mock or live) response
    mock_status_msg.edit_text.assert_called_once()
    final_text = mock_status_msg.edit_text.call_args[0][0]
    assert "OPENROUTER API KEY MISSING" in final_text or "LOBSTAR AI COUNCIL SYNTHESIS" in final_text

