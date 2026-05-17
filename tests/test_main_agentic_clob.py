import logging

import pytest

from main_agentic_clob import (
    build_access_control,
    parse_private_chat_ids,
    telegram_single_instance_lock,
)
from utils.logging_setup import TelegramTokenRedactionFilter
from utils.exceptions import QuantFatal


def test_telegram_token_redaction_filter_masks_formatted_args() -> None:
    record = logging.LogRecord(
        name="httpx",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="HTTP Request: POST %s",
        args=("https://api.telegram.org/bot123456:SECRET/sendMessage",),
        exc_info=None,
    )

    TelegramTokenRedactionFilter().filter(record)

    assert "SECRET" not in record.getMessage()
    assert "/bot<redacted>/sendMessage" in record.getMessage()


def test_telegram_single_instance_lock_rejects_second_holder(tmp_path) -> None:
    lock_path = tmp_path / "telegram.lock"
    with telegram_single_instance_lock(lock_path):
        with pytest.raises(QuantFatal):
            with telegram_single_instance_lock(lock_path):
                pass


def test_parse_private_chat_ids() -> None:
    assert parse_private_chat_ids("") is None
    assert parse_private_chat_ids("123, -456,789") == {123, -456, 789}


def test_build_access_control_has_no_default_admins(monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_ADMIN_CHAT_IDS", raising=False)
    monkeypatch.delenv("CHAT_ID", raising=False)

    access_control, chat_id = build_access_control({}, "PAPER")

    assert chat_id is None
    assert access_control.est_admin(123456789) is False
    assert access_control.est_admin(987654321) is False


def test_build_access_control_requires_admins_in_prod(monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_ADMIN_CHAT_IDS", raising=False)
    monkeypatch.delenv("CHAT_ID", raising=False)

    with pytest.raises(QuantFatal):
        build_access_control({}, "PROD")
