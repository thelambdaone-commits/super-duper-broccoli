import os
import tempfile
import time

import pytest

from utils.data_archiver import DataArchiver


@pytest.fixture
def temp_dirs() -> dict:
    with tempfile.TemporaryDirectory() as archive, tempfile.TemporaryDirectory() as logs:
        yield {"archive": archive, "logs": logs}


@pytest.fixture
def archiver(temp_dirs: dict) -> DataArchiver:
    return DataArchiver(
        db_path="",
        archive_dir=temp_dirs["archive"],
        log_dir=temp_dirs["logs"],
        hot_retention_days=1,
        warm_retention_days=7,
    )


class TestLogCompression:
    def test_compress_no_old_logs(self, archiver: DataArchiver) -> None:
        result = archiver.compress_logs(older_than_days=30)
        assert result["status"] == "SKIPPED"

    def test_compress_old_logs(self, archiver: DataArchiver, temp_dirs: dict) -> None:
        old_log = os.path.join(temp_dirs["logs"], "test_old.log")
        with open(old_log, "w") as f:
            f.write("old log content\n")
        old_ts = time.time() - 4 * 86400
        os.utime(old_log, (old_ts, old_ts))

        result = archiver.compress_logs(older_than_days=3)
        assert result["status"] == "OK"
        assert result["files_compressed"] == 1
        assert os.path.exists(result["archive"])
        assert not os.path.exists(old_log)

    def test_compress_recent_logs_skipped(self, archiver: DataArchiver, temp_dirs: dict) -> None:
        recent_log = os.path.join(temp_dirs["logs"], "recent.log")
        with open(recent_log, "w") as f:
            f.write("recent content\n")

        result = archiver.compress_logs(older_than_days=3)
        assert result["status"] == "SKIPPED"
        assert os.path.exists(recent_log)


class TestArchiveCleanup:
    def test_clean_warm_archives(self, archiver: DataArchiver, temp_dirs: dict) -> None:
        old_file = os.path.join(temp_dirs["archive"], "old_archive.parquet")
        with open(old_file, "w") as f:
            f.write("old")
        old_ts = time.time() - 30 * 86400
        os.utime(old_file, (old_ts, old_ts))

        result = archiver.clean_warm_archives()
        assert result["status"] == "OK"
        assert result["files_removed"] == 1
        assert not os.path.exists(old_file)

    def test_no_old_archives(self, archiver: DataArchiver, temp_dirs: dict) -> None:
        new_file = os.path.join(temp_dirs["archive"], "new_archive.parquet")
        with open(new_file, "w") as f:
            f.write("new")
        result = archiver.clean_warm_archives()
        assert result["files_removed"] == 0
        assert os.path.exists(new_file)


class TestDiskUsage:
    def test_disk_usage_report(self, archiver: DataArchiver, temp_dirs: dict) -> None:
        test_file = os.path.join(temp_dirs["logs"], "test.log")
        with open(test_file, "w") as f:
            f.write("x" * 1024)

        usage = archiver.disk_usage_report()
        assert "logs" in usage
        assert usage["logs"] >= 1024
        assert "feature_store" in usage
        assert "archive" in usage
