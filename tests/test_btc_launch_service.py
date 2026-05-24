from __future__ import annotations

from services.btc_launch_service import BTCDirectionLaunchService, LaunchResult


def test_btc_launch_service_uses_fallback_when_auto_train_disabled(monkeypatch) -> None:
    monkeypatch.setenv("BTC_LAUNCH_AUTO_TRAIN", "false")
    service = BTCDirectionLaunchService(base_model_dir="/tmp/btc-launch-test")

    called = {"launch": 0}

    def _boom(interval: str, direction: str):
        called["launch"] += 1
        raise AssertionError("launch should not be called")

    service.launch = _boom  # type: ignore[assignment]

    result = service.get_or_launch("5m", "up", force_refresh=False)

    assert result.best_variant == "fallback_neutral"
    assert result.strongest_probability == 0.5
    assert called["launch"] == 0


def test_btc_launch_service_reuses_stale_cache_when_auto_train_disabled(monkeypatch) -> None:
    monkeypatch.setenv("BTC_LAUNCH_AUTO_TRAIN", "false")
    service = BTCDirectionLaunchService(base_model_dir="/tmp/btc-launch-test")
    service._cache["5m"] = LaunchResult(
        interval="5m",
        requested_direction="up",
        strongest_direction="up",
        strongest_probability=0.72,
        prob_up=0.72,
        prob_down=0.28,
        best_variant="cached",
        best_val_accuracy=0.61,
        train_samples=100,
        val_samples=20,
        generated_at=0.0,
    )

    result = service.get_or_launch("5m", "down", force_refresh=False)

    assert result.best_variant == "cached"
    assert result.requested_direction == "down"
    assert result.strongest_direction == "up"
