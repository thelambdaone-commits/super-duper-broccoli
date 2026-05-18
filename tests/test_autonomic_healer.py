from __future__ import annotations

import os
import time
import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest
from pathlib import Path
from core.autonomic_healer import LobstarAutonomicHealer


class FakeBroadcaster:
    def __init__(self):
        self.diffuser_alerte_risque_au_canal = AsyncMock(return_value=True)


@pytest.fixture
def temp_log_file(tmp_path: Path) -> str:
    log_file = tmp_path / "app.log"
    log_file.touch()
    return str(log_file)


def test_autonomic_healer_initialization(temp_log_file: str) -> None:
    healer = LobstarAutonomicHealer(log_file_path=temp_log_file)
    assert healer.log_path == temp_log_file
    assert healer.broadcaster is None
    assert healer._last_position == 0
    assert "ALCHEMY_RPC_TIMEOUT" in healer.signatures_erreurs


def test_autonomic_healer_scans_and_detects_errors(temp_log_file: str) -> None:
    healer = LobstarAutonomicHealer(log_file_path=temp_log_file)

    with open(temp_log_file, "a", encoding="utf-8") as f:
        f.write("2026-05-17 12:00:00 [ERROR] Timeout connecting to Alchemy Polygon RPC node\n")
        f.write("2026-05-17 12:01:00 [INFO] Normal event\n")
        f.write("2026-05-17 12:02:00 [ERROR] json.decoder.JSONDecodeError from microfish scraper\n")

    detected = healer.analyser_nouveaux_logs()
    assert "ALCHEMY_RPC_TIMEOUT" in detected
    assert "MICROFISH_PARSING_ERROR" in detected
    assert len(detected) == 2

    # Second scan with no new lines
    assert len(healer.analyser_nouveaux_logs()) == 0

    # Append new line and scan again
    with open(temp_log_file, "a", encoding="utf-8") as f:
        f.write("2026-05-17 12:03:00 [CRITICAL] database is locked during ledger write\n")

    detected_new = healer.analyser_nouveaux_logs()
    assert "SQLITE_WAL_LOCKED" in detected_new
    assert len(detected_new) == 1


@pytest.mark.asyncio
async def test_autonomic_healer_cooldown(temp_log_file: str) -> None:
    healer = LobstarAutonomicHealer(log_file_path=temp_log_file)
    healer._repair_cooldown = 1.0

    # First attempt should run
    result1 = await healer.deployer_correctif_autonome("MEMORY_LEAK_DETECTION")
    assert result1["statut"] == "REPAIRED"

    # Second immediate attempt should skip due to cooldown
    result2 = await healer.deployer_correctif_autonome("MEMORY_LEAK_DETECTION")
    assert result2["statut"] == "SKIPPED"
    assert result2["raison"] == "En cooldown"

    # Sleep past cooldown and try again
    await asyncio.sleep(1.1)
    result3 = await healer.deployer_correctif_autonome("MEMORY_LEAK_DETECTION")
    assert result3["statut"] == "REPAIRED"


@pytest.mark.asyncio
async def test_autonomic_healer_rpc_remediation(temp_log_file: str, monkeypatch: pytest.MonkeyPatch) -> None:
    healer = LobstarAutonomicHealer(log_file_path=temp_log_file)
    
    # Backup not set
    monkeypatch.delenv("BACKUP_QUICKNODE_RPC_URL", raising=False)
    result_fail = await healer.deployer_correctif_autonome("ALCHEMY_RPC_TIMEOUT")
    assert result_fail["statut"] == "FAILED"
    assert "manquante" in result_fail["details"]

    # Backup set
    monkeypatch.setenv("BACKUP_QUICKNODE_RPC_URL", "https://quicknode-backup.polygon")
    healer._repaired_incidents.clear()
    result_ok = await healer.deployer_correctif_autonome("ALCHEMY_RPC_TIMEOUT")
    assert result_ok["statut"] == "REPAIRED"
    assert os.environ.get("POLYGON_RPC_URL") == "https://quicknode-backup.polygon"


@pytest.mark.asyncio
async def test_autonomic_healer_sqlite_wal_remediation(temp_log_file: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    healer = LobstarAutonomicHealer(log_file_path=temp_log_file)
    
    # Create fake WAL files in memory or mock paths
    db_dir = tmp_path / "user_data" / "data"
    db_dir.mkdir(parents=True, exist_ok=True)
    
    shm_file = db_dir / "ledger.db-shm"
    wal_file = db_dir / "ledger.db-wal"
    shm_file.touch()
    wal_file.touch()
    
    # Patch remediator db directory to use our temp path
    def mock_repair_sqlite_wal():
        files_to_remove = [str(shm_file), str(wal_file)]
        removed_count = 0
        for f in files_to_remove:
            if os.path.exists(f):
                os.remove(f)
                removed_count += 1
        return {
            "statut": "REPAIRED",
            "action": "FLUSHED_WAL_SHARED_MEMORY",
            "details": f"{removed_count} files removed"
        }
        
    monkeypatch.setitem(healer.remediation_actions, "SQLITE_WAL_LOCKED", mock_repair_sqlite_wal)
    
    result = await healer.deployer_correctif_autonome("SQLITE_WAL_LOCKED")
    assert result["statut"] == "REPAIRED"
    assert not shm_file.exists()
    assert not wal_file.exists()


@pytest.mark.asyncio
async def test_autonomic_healer_web_scraper_and_clob_remediation(temp_log_file: str) -> None:
    healer = LobstarAutonomicHealer(log_file_path=temp_log_file)

    # Scraper buffer reset
    result_scraper = await healer.deployer_correctif_autonome("MICROFISH_PARSING_ERROR")
    assert result_scraper["statut"] == "REPAIRED"
    assert os.environ.get("MICROFISH_BUFFER_FLUSHED") == "true"

    # WebSocket CLOB reconnect request
    result_clob = await healer.deployer_correctif_autonome("POLYMARKET_CLOB_DISCONNECTION")
    assert result_clob["statut"] == "REPAIRED"
    assert os.environ.get("FORCE_CLOB_RECONNECT") == "true"


@pytest.mark.asyncio
async def test_autonomic_healer_unknown_error_remediation(temp_log_file: str) -> None:
    healer = LobstarAutonomicHealer(log_file_path=temp_log_file)
    result = await healer.deployer_correctif_autonome("UNKNOWN_PANIC")
    assert result["statut"] == "UNKNOWN_ERROR"


@pytest.mark.asyncio
async def test_autonomic_healer_notifications(temp_log_file: str) -> None:
    broadcaster = FakeBroadcaster()
    healer = LobstarAutonomicHealer(log_file_path=temp_log_file, broadcaster=broadcaster)

    result = await healer.deployer_correctif_autonome("MEMORY_LEAK_DETECTION")
    assert result["statut"] == "REPAIRED"
    broadcaster.diffuser_alerte_risque_au_canal.assert_awaited_once()


@pytest.mark.asyncio
async def test_autonomic_healer_scan_loop_graceful_cancel(temp_log_file: str) -> None:
    healer = LobstarAutonomicHealer(log_file_path=temp_log_file)
    
    # Execute loop and cancel it immediately
    task = asyncio.create_task(healer.scan_et_guerir_continu(interval_seconds=0.01))
    await asyncio.sleep(0.02)
    task.cancel()
    
    try:
        await task
    except asyncio.CancelledError:
        pass
    
    # Assert it terminated gracefully without exception
    assert task.done()
