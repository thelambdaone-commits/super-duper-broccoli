import httpx

from utils.polymarket_client import PolymarketClient


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_safe_request_uses_exponential_backoff(monkeypatch):
    client = PolymarketClient()
    sleeps = []
    attempts = {"count": 0}

    def fake_request(method, url, **kwargs):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise httpx.NetworkError("temporary outage")
        return _FakeResponse({"ok": True})

    monkeypatch.setattr(client._http, "request", fake_request)
    monkeypatch.setattr("utils.polymarket_client.time.sleep", sleeps.append)

    try:
        assert client._safe_request("GET", "https://example.test") == {"ok": True}
    finally:
        client.close()

    assert attempts["count"] == 3
    assert sleeps == [1.0, 2.0]
