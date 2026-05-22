import json
from unittest.mock import Mock, patch

from utils.openviking_adapter import build_openviking_context, search_context


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


def test_search_context_falls_back_until_results():
    calls = []

    def fake_urlopen(req, timeout=5.0):
        calls.append(req.full_url)
        if req.full_url.endswith("/api/v1/search/search"):
            raise OSError("not ready")
        return _FakeResponse({"results": [{"uri": "viking://notes/1", "score": 0.91}]})

    with patch("urllib.request.urlopen", side_effect=fake_urlopen), patch.dict(
        "os.environ",
        {
            "OPENVIKING_ENABLED": "true",
            "OPENVIKING_URL": "http://127.0.0.1:1933",
        },
        clear=False,
    ):
        results = search_context("btc 15m", limit=3)

    assert len(results) == 1
    assert results[0]["uri"] == "viking://notes/1"
    assert calls[0].endswith("/api/v1/search/search")
    assert calls[1].endswith("/api/v1/search/find")


def test_build_openviking_context_disabled_by_default():
    with patch.dict("os.environ", {}, clear=True):
        context = build_openviking_context("btc 15m")

    assert context["enabled"] is False
    assert context["available"] is False
    assert context["results"] == []


def test_build_openviking_context_reports_results_when_enabled():
    with patch("urllib.request.urlopen", return_value=_FakeResponse({"results": [{"id": "a"}]})), patch.dict(
        "os.environ",
        {
            "OPENVIKING_ENABLED": "1",
            "OPENVIKING_URL": "http://127.0.0.1:1933",
        },
        clear=False,
    ):
        context = build_openviking_context("project memory", limit=1)

    assert context["enabled"] is True
    assert context["available"] is True
    assert context["result_count"] == 1
    assert context["results"][0]["id"] == "a"
