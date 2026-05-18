import json
import os
import tempfile

import pytest

from utils.binance_websocket import BinanceWebSocketListener
from utils.feature_store import FeatureStore


@pytest.fixture
def feature_store() -> FeatureStore:
    path = os.path.join(tempfile.gettempdir(), "test_binance_websocket.duckdb")
    if os.path.exists(path):
        os.remove(path)
    store = FeatureStore(path)
    yield store
    store.close()
    if os.path.exists(path):
        os.remove(path)


@pytest.mark.asyncio
async def test_binance_websocket_parses_book_ticker_and_persists(feature_store: FeatureStore) -> None:
    listener = BinanceWebSocketListener(symbols=["BTCUSDT"], store=feature_store)
    payload = json.dumps(
        {
            "stream": "btcusdt@bookTicker",
            "data": {
                "s": "BTCUSDT",
                "b": "100.00",
                "a": "100.10",
                "B": "10.0",
                "A": "12.0",
                "E": 1_700_000_000_000,
            },
        }
    )

    snapshots = listener.parse_message(payload)

    assert len(snapshots) == 1
    assert snapshots[0]["ticker"] == "BTCUSDT"
    assert snapshots[0]["mid_price"] == pytest.approx(100.05)
    assert snapshots[0]["spread_bps"] == pytest.approx(9.995, rel=1e-3)

    persisted = await listener.handle_message(payload)
    assert len(persisted) == 1

    history = feature_store.get_feature_history("BTCUSDT", "mid_price")
    assert history
    assert history[0]["value"] == pytest.approx(100.05)
    events = feature_store.get_web_events(event_type="book_ticker")
    assert events
    assert events[0]["source"] == "binance_ws"
