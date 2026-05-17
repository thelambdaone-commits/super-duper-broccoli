import json
import os
import tempfile
from unittest.mock import patch

import pytest

from scrapers.clob_listener import CLOBListener
from scrapers.web_scraper import WebScraper, WebScraperConfig
from utils.credential_manager import CredentialManager
from utils.feature_store import FeatureStore
from utils.output_formatter import OutputFormatter, TelegramOutputFormatter


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeAsyncClient:
    def __init__(self, payloads):
        self.payloads = list(payloads)

    async def get(self, *args, **kwargs):
        return FakeResponse(self.payloads.pop(0))


@pytest.fixture
def feature_store() -> FeatureStore:
    path = os.path.join(tempfile.gettempdir(), "test_web_scraping_architecture.duckdb")
    if os.path.exists(path):
        os.remove(path)
    store = FeatureStore(path)
    yield store
    store.close()
    if os.path.exists(path):
        os.remove(path)


@pytest.mark.asyncio
async def test_web_scraper_detects_and_persists_market_events(feature_store: FeatureStore) -> None:
    first = [
        {
            "slug": "btc-above-100k",
            "conditionId": "0xabc",
            "active": True,
            "closed": False,
            "volume": 100.0,
        }
    ]
    second = [
        {
            "slug": "btc-above-100k",
            "conditionId": "0xabc",
            "active": True,
            "closed": True,
            "volume": 125.0,
        }
    ]
    scraper = WebScraper(
        store=feature_store,
        config=WebScraperConfig(min_volume_delta=10.0),
        client=FakeAsyncClient([first, second]),
    )

    seen = await scraper.poll_once()
    changed = await scraper.poll_once()

    assert [event["event_type"] for event in seen] == ["market_seen"]
    assert [event["event_type"] for event in changed] == ["volume_change", "resolution_seen"]
    stored = feature_store.get_web_events()
    assert [event["event_type"] for event in stored] == [
        "market_seen",
        "volume_change",
        "resolution_seen",
    ]


@pytest.mark.asyncio
async def test_clob_listener_parses_and_persists_orderbook_snapshot(feature_store: FeatureStore) -> None:
    listener = CLOBListener(store=feature_store)
    payload = json.dumps(
        {
            "asset_id": "token-yes",
            "market": "0xmarket",
            "timestamp": 1_700_000_000_000,
            "bids": [{"price": "0.49", "size": "100"}, {"price": "0.48", "size": "50"}],
            "asks": [{"price": "0.51", "size": "80"}, {"price": "0.52", "size": "20"}],
        }
    )

    snapshots = await listener.handle_message(payload)

    assert len(snapshots) == 1
    assert snapshots[0]["mid_price"] == pytest.approx(0.50)
    assert snapshots[0]["spread_bps"] == pytest.approx(400.0)
    assert feature_store.get_feature_history("token-yes", "mid_price")[0]["value"] == pytest.approx(0.50)
    assert feature_store.get_web_events(event_type="orderbook_snapshot")


def test_output_formatter_is_terminal_clean_and_alias_compatible() -> None:
    formatter = OutputFormatter()
    text = formatter.format_signal_alert(
        {
            "ticker": "BTC`YES",
            "side": "BUY",
            "p_market": 0.51,
            "p_real": 0.61,
            "edge": 0.10,
            "kelly": 0.05,
        }
    )

    assert TelegramOutputFormatter is OutputFormatter
    assert "== LOBSTAR QUANT SIGNAL ==" in text
    assert "*" not in text
    assert "```" not in text
    assert "p_market" in text


def test_credential_manager_ephemeral_session_does_not_write_disk(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("POLYMARKET_WALLET_ADDRESS", raising=False)
    manager = CredentialManager(encryption_key=FernetKey.TEST_KEY)
    private_key = "0x" + "1" * 64

    with patch("utils.credential_manager.derive_clob_credentials") as derive:
        derive.return_value = {
            "CLOB_API_KEY": "api",
            "CLOB_API_SECRET": "secret",
            "CLOB_API_PASSPHRASE": "pass",
            "address": "0xwallet",
        }
        with patch.object(manager, "encrypt_and_save") as save:
            session = manager.derive_ephemeral_clob_session(private_key)

    save.assert_not_called()
    assert session["CLOB_PRIVATE_KEY"] == private_key
    assert session["POLYMARKET_WALLET_ADDRESS"] == "0xwallet"

    manager.destroy_secret_map(session)
    assert session == {}


class FernetKey:
    TEST_KEY = "F9U0WUdQxZpg_NTGWJm6_u8x2J1r1JnjBIQI4cfLz68="
