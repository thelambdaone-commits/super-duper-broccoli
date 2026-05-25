from __future__ import annotations

from services.prometheus_exporter import PrometheusExporter


def test_prometheus_exporter_skips_start_when_port_in_use(monkeypatch) -> None:
    exporter = PrometheusExporter(port=8000)

    monkeypatch.setattr(exporter, "_port_in_use", lambda: True)

    called = {"start_http_server": False}

    def _fail_start_http_server(port: int) -> None:
        called["start_http_server"] = True

    monkeypatch.setattr("services.prometheus_exporter.start_http_server", _fail_start_http_server)

    exporter.start()

    assert called["start_http_server"] is False
