import logging
import os
import tarfile
import time
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger("DataArchiver")


ARCHIVE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "user_data", "archive"
)
LOG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "logs"
)
FEATURE_STORE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "data", "feature_store.duckdb"
)


class DataArchiver:
    def __init__(
        self,
        db_path: str = FEATURE_STORE_PATH,
        archive_dir: str = ARCHIVE_DIR,
        log_dir: str = LOG_DIR,
        hot_retention_days: int = 2,
        warm_retention_days: int = 30,
        feature_store: Optional[Any] = None,
    ) -> None:
        self.db_path = db_path
        self.archive_dir = archive_dir
        self.log_dir = log_dir
        self.hot_retention = hot_retention_days
        self.warm_retention = warm_retention_days
        self._fs_instance = feature_store
        os.makedirs(self.archive_dir, exist_ok=True)

    def _get_feature_store(self):
        if self._fs_instance:
            return self._fs_instance
        from utils.feature_store import FeatureStore
        return FeatureStore(db_path=self.db_path)

    def archive_microstructure(self) -> dict:
        if not os.path.exists(self.db_path) and not self._fs_instance:
            logger.warning(f"Feature store not found: {self.db_path}")
            return {"status": "SKIPPED", "reason": "db_not_found"}

        fs = self._get_feature_store()
        
        # Security check: don't archive if we are on a fallback or read-only DB
        if fs.is_fallback:
            logger.warning("Archiving skipped: FeatureStore is in fallback (memory) mode.")
            return {"status": "SKIPPED", "reason": "db_fallback_mode"}
            
        # If we are read-only, we can export but NOT purge. 
        # For safety, we skip the whole cycle unless we have R/W access.
        if fs.is_read_only:
            logger.warning("Archiving skipped: FeatureStore is in read-only mode.")
            return {"status": "SKIPPED", "reason": "db_read_only"}

        cutoff = time.time() - self.hot_retention * 86400
        date_str = datetime.fromtimestamp(cutoff).strftime("%Y%m%d")
        tables = ["market_microstructure", "features_computed", "signals_ingested", "decisions_log"]
        total_rows = 0
        exported = []

        for table in tables:
            parquet_path = os.path.join(
                self.archive_dir, f"{table}_before_{date_str}.parquet"
            )
            rows = fs.export_to_parquet(table, parquet_path, cutoff)
            if rows > 0:
                total_rows += rows
                exported.append(table)

        if total_rows > 0:
            fs.purge_before(cutoff)
        
        # Don't close if it was passed externally
        if not self._fs_instance:
            fs.close()

        result = {
            "status": "OK",
            "cutoff_date": date_str,
            "tables_exported": exported,
            "total_rows_archived": total_rows,
        }
        logger.info(f"Microstructure archived: {result}")
        return result

    def compress_logs(self, older_than_days: int = 3) -> dict:
        if not os.path.exists(self.log_dir):
            return {"status": "SKIPPED", "reason": "log_dir_not_found"}

        cutoff = time.time() - older_than_days * 86400
        archive_name = os.path.join(
            self.archive_dir,
            f"logs_archive_{datetime.now().strftime('%Y%m%d_%H%M%S')}.tar.gz"
        )
        files_to_archive = []

        for f in os.listdir(self.log_dir):
            file_path = os.path.join(self.log_dir, f)
            if os.path.isfile(file_path) and f.endswith((".log", ".txt", ".json")):
                mtime = os.path.getmtime(file_path)
                if mtime < cutoff:
                    files_to_archive.append(file_path)

        if not files_to_archive:
            return {"status": "SKIPPED", "reason": "no_old_logs"}

        with tarfile.open(archive_name, "w:gz") as tar:
            for file_path in files_to_archive:
                tar.add(file_path, arcname=os.path.basename(file_path))

        if os.path.exists(archive_name) and os.path.getsize(archive_name) > 0:
            for file_path in files_to_archive:
                os.remove(file_path)
            result = {
                "status": "OK",
                "archive": archive_name,
                "files_compressed": len(files_to_archive),
                "size_bytes": os.path.getsize(archive_name),
            }
            logger.info(f"Logs archived: {result}")
            return result

        return {"status": "ERROR", "reason": "archive_creation_failed"}

    def clean_warm_archives(self) -> dict:
        if not os.path.exists(self.archive_dir):
            return {"status": "SKIPPED", "reason": "archive_dir_not_found"}

        cutoff = time.time() - self.warm_retention * 86400
        removed = 0
        for f in os.listdir(self.archive_dir):
            file_path = os.path.join(self.archive_dir, f)
            if os.path.isfile(file_path) and f.endswith((".parquet", ".tar.gz")):
                mtime = os.path.getmtime(file_path)
                if mtime < cutoff:
                    os.remove(file_path)
                    removed += 1

        result = {"status": "OK", "files_removed": removed}
        if removed:
            logger.info(f"Warm archives cleaned: {result}")
        return result

    def disk_usage_report(self) -> dict:
        usage = {}
        for label, path in [
            ("feature_store", self.db_path),
            ("archive", self.archive_dir),
            ("logs", self.log_dir),
        ]:
            if path and os.path.exists(path):
                if os.path.isfile(path):
                    size = os.path.getsize(path)
                else:
                    size = sum(
                        os.path.getsize(os.path.join(dirpath, f))
                        for dirpath, _, filenames in os.walk(path)
                        for f in filenames
                    )
                usage[label] = size
            else:
                usage[label] = 0
        return usage

    def run_maintenance_cycle(self) -> dict:
        results = {
            "microstructure": self.archive_microstructure(),
            "logs": self.compress_logs(),
            "cleanup": self.clean_warm_archives(),
            "disk_usage": self.disk_usage_report(),
        }
        return results
