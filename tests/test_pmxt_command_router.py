from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from interface.command_router import CommandRouter


@pytest.mark.asyncio
async def test_dev_pmxt_status_routes_to_service() -> None:
    service = SimpleNamespace(format_status_html=MagicMock(return_value="PMXT STATUS"))
    listener = SimpleNamespace(
        application=MagicMock(),
        _check_admin_auth=AsyncMock(return_value=True),
        reply_to=AsyncMock(),
        _pmxt_service=service,
    )
    router = CommandRouter(listener)
    update = MagicMock()
    context = SimpleNamespace(args=["pmxt", "status"])

    await router._cmd_dev(update, context)

    listener.reply_to.assert_awaited_once()
    args, _ = listener.reply_to.await_args
    assert args[0] == "PMXT STATUS"
