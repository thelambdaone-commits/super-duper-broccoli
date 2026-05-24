from __future__ import annotations

from interface.telegram_listener import TelegramListener


class StubRunner:
    def get_job_stats(self) -> dict:
        return {
            "slow_job": {
                "resource_profile": "heavy",
                "run_count": 4,
                "skip_count": 3,
                "avg_duration_ms": 120.5,
                "max_duration_ms": 260.0,
            },
            "fast_job": {
                "resource_profile": "latency",
                "run_count": 25,
                "skip_count": 0,
                "avg_duration_ms": 4.2,
                "max_duration_ms": 9.1,
            },
        }


def test_format_runner_status_renders_top_jobs() -> None:
    listener = TelegramListener(
        bot_token="token",
        on_signal=lambda signal: None,
        chat_id=None,
        private_chat_ids={123},
        admin_chat_ids={123},
    )
    listener._runner = StubRunner()

    rendered = listener._format_runner_status()

    assert "<b>RUNNER</b>" in rendered
    assert "slow_job" in rendered
    assert "[heavy]" in rendered
    assert "skip=<code>3</code>" in rendered
    assert "avg=<code>120.5ms</code>" in rendered
