import logging
import os
import json
import time
from datetime import datetime
from typing import Any, Optional
import duckdb

logger = logging.getLogger("SnapshotManager")

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "user_data", "data")
SNAPSHOT_DB_PATH = os.path.join(DB_DIR, "snapshots.duckdb")

class SnapshotManager:
    def __init__(self, db_path: str = SNAPSHOT_DB_PATH) -> None:
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        try:
            self.conn = duckdb.connect(db_path)
        except duckdb.IOException as e:
            if "lock" in str(e).lower():
                logger.warning(f"⚠️ DuckDB lock conflict on {db_path}. Falling back to in-memory database (:memory:) to prevent crashes...")
                self.conn = duckdb.connect(":memory:")
            else:
                raise
        self._init_db()

    def _init_db(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS snapshots (
                timestamp DOUBLE,
                date TIMESTAMP,
                category VARCHAR,
                component VARCHAR,
                data VARCHAR,
                tags VARCHAR[]
            )
        """)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_snap_ts ON snapshots (timestamp)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_snap_cat ON snapshots (category)")

    def capture(self, category: str, component: str, data: dict, tags: Optional[list[str]] = None):
        """Captures a state snapshot."""
        try:
            from utils.security_utils import encrypt_data
            ts = time.time()
            dt = datetime.utcnow()
            data_json = json.dumps(data, default=str)
            # Encrypt sensitive data blob
            encrypted_data = encrypt_data(data_json)
            tags_list = tags if tags else []
            
            self.conn.execute(
                "INSERT INTO snapshots VALUES (?, ?, ?, ?, ?, ?)",
                (ts, dt, category, component, encrypted_data, tags_list)
            )
        except Exception as e:
            logger.error(f"Failed to capture snapshot [{category}:{component}]: {e}")

    def get_latest(self, category: str, component: Optional[str] = None) -> Optional[dict]:
        query = "SELECT data FROM snapshots WHERE category = ?"
        params = [category]
        if component:
            query += " AND component = ?"
            params.append(component)
        query += " ORDER BY timestamp DESC LIMIT 1"
        
        from utils.security_utils import decrypt_data
        res = self.conn.execute(query, params).fetchone()
        if res:
            try:
                decrypted = decrypt_data(res[0])
                return json.loads(decrypted)
            except Exception:
                return json.loads(res[0]) # Fallback for unencrypted
        return None

    def get_range(self, start_ts: float, end_ts: float, category: Optional[str] = None) -> list[dict]:
        query = "SELECT timestamp, category, component, data FROM snapshots WHERE timestamp >= ? AND timestamp <= ?"
        params = [start_ts, end_ts]
        if category:
            query += " AND category = ?"
            params.append(category)
        query += " ORDER BY timestamp ASC"
        
        from utils.security_utils import decrypt_data
        rows = self.conn.execute(query, params).fetchall()
        results = []
        for r in rows:
            try:
                decrypted = decrypt_data(r[3])
                data = json.loads(decrypted)
            except Exception:
                data = json.loads(r[3])
            results.append({"timestamp": r[0], "category": r[1], "component": r[2], "data": data})
        return results

    def export_session(self, output_path: str, start_ts: float = 0, end_ts: float = 0):
        """Exports a session to Parquet for offline analysis/replay."""
        if end_ts == 0: end_ts = time.time()
        self.conn.execute(
            f"COPY (SELECT * FROM snapshots WHERE timestamp >= {start_ts} AND timestamp <= {end_ts}) TO '{output_path}' (FORMAT PARQUET)"
        )
        logger.info(f"Session exported to {output_path}")

    def close(self):
        self.conn.close()

# Global instance for easy access
_manager: Optional[SnapshotManager] = None

def get_snapshot_manager() -> SnapshotManager:
    global _manager
    if _manager is None:
        _manager = SnapshotManager()
    return _manager
