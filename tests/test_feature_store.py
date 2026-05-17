import os
import tempfile
import time

import pytest

from utils.feature_store import FeatureStore


@pytest.fixture
def db_path() -> str:
    path = os.path.join(tempfile.gettempdir(), f"test_fs_{int(time.time() * 1e6)}.duckdb")
    if os.path.exists(path):
        os.remove(path)
    yield path
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def store(db_path: str) -> FeatureStore:
    return FeatureStore(db_path=db_path)


class TestFeatureStoreSchema:
    def test_init_creates_tables(self, store: FeatureStore) -> None:
        stats = store.get_stats()
        assert "market_microstructure" in stats
        assert "features_computed" in stats
        assert "signals_ingested" in stats
        assert "decisions_log" in stats

    def test_stats_returns_zero_on_empty(self, store: FeatureStore) -> None:
        stats = store.get_stats()
        for v in stats.values():
            assert v == 0


class TestMicrostructure:
    def test_record_microstructure(self, store: FeatureStore) -> None:
        sid = store.record_microstructure(
            ticker="SOL",
            bid_volume=1000.0,
            ask_volume=800.0,
            spread=0.02,
            mid_price=0.65,
            order_imbalance=0.2,
        )
        assert sid > 0
        stats = store.get_stats()
        assert stats["market_microstructure"] == 1

    def test_get_microstructure_range(self, store: FeatureStore) -> None:
        store.record_microstructure("SOL", 100.0, 80.0, 0.01, 0.5, 0.1)
        store.record_microstructure("SOL", 200.0, 150.0, 0.02, 0.55, 0.2)
        now = time.time()
        rows = store.get_microstructure_range(now - 10, now + 10)
        assert len(rows) == 2

    def test_get_microstructure_range_filtered(self, store: FeatureStore) -> None:
        store.record_microstructure("SOL", 100.0, 80.0, 0.01, 0.5, 0.1)
        store.record_microstructure("BTC", 50.0, 40.0, 0.01, 0.5, 0.1)
        now = time.time()
        rows = store.get_microstructure_range(now - 10, now + 10, ticker="SOL")
        assert len(rows) == 1
        assert rows[0]["ticker"] == "SOL"


class TestFeatures:
    def test_record_and_retrieve_feature(self, store: FeatureStore) -> None:
        store.record_feature("SOL", "oi_5min", 0.35)
        store.record_feature("SOL", "oi_5min", 0.42)
        history = store.get_feature_history("SOL", "oi_5min")
        assert len(history) == 2
        assert history[0]["value"] == pytest.approx(0.35)
        assert history[1]["value"] == pytest.approx(0.42)

    def test_feature_history_limit(self, store: FeatureStore) -> None:
        for i in range(10):
            store.record_feature("SOL", "tam", float(i) / 10.0)
        history = store.get_feature_history("SOL", "tam", limit=3)
        assert len(history) == 3

    def test_feature_history_until_ts_excludes_future_rows(
        self, store: FeatureStore
    ) -> None:
        store.record_feature("SOL", "oi", 0.1, timestamp=100.0)
        store.record_feature("SOL", "oi", 0.2, timestamp=200.0)
        store.record_feature("SOL", "oi", 0.3, timestamp=300.0)
        history = store.get_feature_history("SOL", "oi", until_ts=200.0)
        assert [row["value"] for row in history] == pytest.approx([0.1, 0.2])


class TestSignals:
    def test_record_signal(self, store: FeatureStore) -> None:
        sid = store.record_signal(
            source="regex", ticker="SOL", side="BUY",
            price=0.50, size=100.0, confidence=0.8,
            raw_text="BUY SOL @ 0.50", regime_label="LOW_VOLATILITY",
        )
        assert sid > 0
        stats = store.get_stats()
        assert stats["signals_ingested"] == 1

    def test_replay_signals(self, store: FeatureStore) -> None:
        store.record_signal("regex", "SOL", "BUY", 0.50, 100, 0.8)
        store.record_signal("lobstar_llm", "BTC", "SELL", 0.60, 50, 0.9)
        signals = store.replay_signals(since_timestamp=0.0, limit=10)
        assert len(signals) == 2
        assert signals[0]["ticker"] == "SOL"
        assert signals[1]["ticker"] == "BTC"


class TestDecisions:
    def test_record_decision(self, store: FeatureStore) -> None:
        store.record_decision(
            mode="PAPER", ticker="SOL", side="BUY",
            price=0.50, sized=100.0, executed_size=100.0,
            kelly_pct=12.5, regime_label="LOW_VOLATILITY",
            net_beta_pct=3.2, authorized=True, reason="PAPER_OK",
        )
        stats = store.get_stats()
        assert stats["decisions_log"] == 1

    def test_replay_decisions(self, store: FeatureStore) -> None:
        store.record_decision("PAPER", "SOL", "BUY", 0.5, 100, 100)
        store.record_decision("PROD", "BTC", "SELL", 0.6, 50, 50)
        decisions = store.replay_decisions(since_timestamp=0.0, limit=10)
        assert len(decisions) == 2


class TestReplayCursor:
    def test_set_and_get_cursor(self, store: FeatureStore) -> None:
        store.set_replay_cursor(last_timestamp=1234567890.0, last_signal_id=42)
        cursor = store.get_replay_cursor()
        assert cursor["last_timestamp"] == 1234567890.0
        assert cursor["last_signal_id"] == 42
        assert cursor["mode"] == "REPLAY"

    def test_default_cursor(self, store: FeatureStore) -> None:
        cursor = store.get_replay_cursor()
        assert cursor["last_timestamp"] == 0.0
        assert cursor["last_signal_id"] == 0


class TestPurge:
    def test_purge_before(self, store: FeatureStore) -> None:
        store.record_feature("SOL", "oi", 0.5)
        store.record_signal("regex", "SOL", "BUY", 0.5, 100, 0.8)
        before = time.time() + 10
        deleted = store.purge_before(before)
        assert deleted >= 2
        stats = store.get_stats()
        assert stats["features_computed"] == 0
        assert stats["signals_ingested"] == 0

    def test_purge_preserves_recent(self, store: FeatureStore) -> None:
        store.record_feature("SOL", "oi", 0.5)
        before = time.time() - 10
        deleted = store.purge_before(before)
        assert deleted == 0
        stats = store.get_stats()
        assert stats["features_computed"] == 1
