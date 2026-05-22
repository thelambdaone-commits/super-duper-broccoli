from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from core.orchestrator import LobstarOrchestrator


@pytest.mark.asyncio
async def test_wallet_disconnect_callback_uses_attached_wallet_vault() -> None:
    vault = Mock()
    wallet_manager = SimpleNamespace(vault=vault)
    orchestrator = object.__new__(LobstarOrchestrator)
    orchestrator.wallet_manager = wallet_manager
    orchestrator.history = None
    orchestrator.ledger = None

    query = SimpleNamespace(
        data="wallet_disconnect_confirmed",
        from_user=SimpleNamespace(id=123),
        message=SimpleNamespace(chat_id=456, message_id=789),
        answer=AsyncMock(),
    )
    update = SimpleNamespace(callback_query=query)
    context = SimpleNamespace(bot=SimpleNamespace(edit_message_text=AsyncMock()))

    await orchestrator.handle_wallet_callback(update, context)

    query.answer.assert_awaited_once()
    vault.supprimer_wallet_session.assert_called_once_with(456)
    context.bot.edit_message_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_wallet_reveal_key_never_sends_private_key() -> None:
    orchestrator = object.__new__(LobstarOrchestrator)
    orchestrator.wallet_manager = None
    orchestrator.history = None
    orchestrator.ledger = None

    query = SimpleNamespace(
        data="wallet_reveal_key_confirmed",
        from_user=SimpleNamespace(id=123),
        message=SimpleNamespace(chat_id=456, message_id=789),
        answer=AsyncMock(),
    )
    update = SimpleNamespace(callback_query=query)
    context = SimpleNamespace(bot=SimpleNamespace(edit_message_text=AsyncMock()))

    await orchestrator.handle_wallet_callback(update, context)

    text = context.bot.edit_message_text.await_args.kwargs["text"]
    assert "0x" not in text
    assert "ne peut pas être affichée" in text
