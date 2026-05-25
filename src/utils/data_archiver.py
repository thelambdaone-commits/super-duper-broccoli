import logging
import os
import json
import shutil
import tarfile
import time
from datetime import datetime
from pathlib import Path
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

    @staticmethod
    def _parquet_summary(path: Path) -> dict[str, Any]:
        try:
            import pyarrow.parquet as pq
        except ImportError:
            return {
                "path": str(path),
                "kind": "parquet",
                "status": "skipped",
                "reason": "pyarrow_not_installed",
                "size_bytes": path.stat().st_size if path.exists() else 0,
            }

        pf = pq.ParquetFile(str(path))
        metadata = pf.metadata
        schema = pf.schema_arrow
        return {
            "path": str(path),
            "kind": "parquet",
            "status": "ok",
            "size_bytes": path.stat().st_size if path.exists() else 0,
            "rows": int(metadata.num_rows) if metadata else 0,
            "row_groups": int(metadata.num_row_groups) if metadata else 0,
            "columns": [field.name for field in schema],
        }

    def archive_polymarket_dataset(
        self,
        source_dir: str,
        dataset_name: str = "Polymarket_data",
        include_sidecars: bool = True,
    ) -> dict[str, Any]:
        source_path = Path(source_dir)
        if not source_path.exists() or not source_path.is_dir():
            return {"status": "SKIPPED", "reason": "source_dir_not_found", "source_dir": str(source_path)}

        snapshot_root = Path(self.archive_dir) / "polymarket_data"
        snapshot_root.mkdir(parents=True, exist_ok=True)
        snapshot_dir = snapshot_root / f"{dataset_name.lower()}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        snapshot_dir.mkdir(parents=True, exist_ok=True)

        candidate_files = [
            "quant.parquet",
            "users.parquet",
            "trades.parquet",
            "markets.parquet",
            "orderfilled.parquet",
            "README.md",
            "LICENSE",
        ]
        entries: list[dict[str, Any]] = []
        total_rows = 0
        total_bytes = 0

        for rel_name in candidate_files:
            src = source_path / rel_name
            if not src.exists() or not src.is_file():
                continue

            size_bytes = src.stat().st_size
            total_bytes += size_bytes
            entry: dict[str, Any] = {
                "name": rel_name,
                "source_path": str(src),
                "size_bytes": size_bytes,
            }

            if src.suffix == ".parquet":
                parquet_summary = self._parquet_summary(src)
                total_rows += int(parquet_summary.get("rows", 0) or 0)
                entry.update(parquet_summary)
            else:
                entry["kind"] = "sidecar"
                entry["status"] = "ok"
                if include_sidecars:
                    dst = snapshot_dir / rel_name
                    shutil.copy2(src, dst)
                    entry["copied_to"] = str(dst)

            entries.append(entry)

        manifest = {
            "dataset_name": dataset_name,
            "source_dir": str(source_path),
            "archived_at": datetime.now().isoformat(),
            "archive_dir": str(snapshot_dir),
            "files": entries,
            "file_count": len(entries),
            "parquet_row_total": total_rows,
            "bytes_scanned": total_bytes,
        }
        manifest_path = snapshot_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

        return {
            "status": "OK",
            "dataset_name": dataset_name,
            "source_dir": str(source_path),
            "archive_dir": str(snapshot_dir),
            "manifest": str(manifest_path),
            "file_count": len(entries),
            "parquet_row_total": total_rows,
            "bytes_scanned": total_bytes,
        }

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
        polymarket_dataset_path = os.getenv("POLYMARKET_DATASET_PATH", "").strip()
        results = {
            "microstructure": self.archive_microstructure(),
            "logs": self.compress_logs(),
            "cleanup": self.clean_warm_archives(),
            "disk_usage": self.disk_usage_report(),
        }
        if polymarket_dataset_path:
            results["polymarket_dataset"] = self.archive_polymarket_dataset(polymarket_dataset_path)
        else:
            results["polymarket_dataset"] = {"status": "SKIPPED", "reason": "POLYMARKET_DATASET_PATH_not_set"}
        return results
