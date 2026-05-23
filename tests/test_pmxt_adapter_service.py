from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from utils.pmxt_adapter_service import PMXTAdapterConfig, PMXTAdapterService


def test_pmxt_service_status_reports_missing_polars(tmp_path: Path) -> None:
    service = PMXTAdapterService(PMXTAdapterConfig(data_dir=tmp_path))

    status = service.status()

    assert status["adapter_files_present"] is True
    assert status["incoming_file_count"] == 0
    assert "polars" in status["dependencies"]


def test_pmxt_service_disabled_cycle_skips(tmp_path: Path) -> None:
    service = PMXTAdapterService(PMXTAdapterConfig(enabled=False, data_dir=tmp_path))

    result = service._run_cycle_blocking(force=False)

    assert result == {"status": "SKIPPED", "reason": "disabled"}

