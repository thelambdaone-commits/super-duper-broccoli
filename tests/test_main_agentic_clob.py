import logging

import pytest

from main_agentic_clob import (
    TelegramTokenRedactionFilter,
    parse_private_chat_ids,
    telegram_single_instance_lock,
)
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
