import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Any, Optional

from utils.exceptions import QuantFatal

logger = logging.getLogger("FeatureStore")


FEATURE_STORE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "user_data", "data", "feature_store.duckdb"
)


class FeatureStore:
    def __init__(self, db_path: str = FEATURE_STORE_PATH) -> None:
        self.db_path = db_path
        self._conn: Any = None
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._connect()
        self._init_schema()

    def _connect(self) -> None:
        try:
            import duckdb
            self._conn = duckdb.connect(self.db_path)
            logger.info(f"FeatureStore connected: {self.db_path}")
        except ImportError:
            raise QuantFatal("duckdb not installed. Install with: pip install duckdb")

    def _init_schema(self) -> None:
        self._conn.execute("""
            CREATE SEQUENCE IF NOT EXISTS seq_snapshot START 1
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS market_microstructure (
                snapshot_id INTEGER PRIMARY KEY DEFAULT nextval('seq_snapshot'),
                timestamp DOUBLE NOT NULL,
                ticker VARCHAR NOT NULL,
                bid_volume FLOAT,
                ask_volume FLOAT,
                spread FLOAT,
                mid_price FLOAT,
                order_imbalance FLOAT,
                depth_imbalance FLOAT,
                queue_velocity FLOAT,
                liquidity_score FLOAT,
                raw_json VARCHAR
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS features_computed (
                feature_id INTEGER PRIMARY KEY DEFAULT nextval('seq_snapshot'),
                timestamp DOUBLE NOT NULL,
                ticker VARCHAR NOT NULL,
                feature_name VARCHAR NOT NULL,
                feature_value FLOAT
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS signals_ingested (
                signal_id INTEGER PRIMARY KEY DEFAULT nextval('seq_snapshot'),
                timestamp DOUBLE NOT NULL,
                source VARCHAR NOT NULL,
                ticker VARCHAR,
                side VARCHAR,
                price FLOAT,
                size FLOAT,
                confidence FLOAT,
                raw_text VARCHAR,
                regime_label VARCHAR,
                decision_json VARCHAR
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS decisions_log (
                decision_id INTEGER PRIMARY KEY DEFAULT nextval('seq_snapshot'),
                timestamp DOUBLE NOT NULL,
                mode VARCHAR NOT NULL,
                ticker VARCHAR,
                side VARCHAR,
                price FLOAT,
                sized FLOAT,
                executed_size FLOAT,
                kelly_pct FLOAT,
                regime_label VARCHAR,
                net_beta_pct FLOAT,
                authorized BOOLEAN,
                reason VARCHAR
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS replay_cursor (
                id INTEGER PRIMARY KEY,
                last_timestamp DOUBLE NOT NULL,
                last_signal_id INTEGER DEFAULT 0,
                mode VARCHAR DEFAULT 'REPLAY'
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS calibration_metrics (
                metric_id INTEGER PRIMARY KEY DEFAULT nextval('seq_snapshot'),
                timestamp DOUBLE NOT NULL,
                ticker VARCHAR,
                model_version VARCHAR,
                raw_brier FLOAT,
                calibrated_brier FLOAT,
                brier_improvement FLOAT,
                n_samples INT,
                fusion_mode VARCHAR
            )
        """)
        self._conn.commit()
        logger.info("FeatureStore schema initialized")

    def record_microstructure(
        self,
        ticker: str,
        bid_volume: float,
        ask_volume: float,
        spread: float,
        mid_price: float,
        order_imbalance: float,
        depth_imbalance: float = 0.0,
        queue_velocity: float = 0.0,
        liquidity_score: float = 0.0,
        raw_json: Optional[dict] = None,
    ) -> int:
        from utils.security_utils import encrypt_data
        ts = time.time()
        encrypted_raw = encrypt_data(json.dumps(raw_json)) if raw_json else None
        self._conn.execute("""
            INSERT INTO market_microstructure
                (timestamp, ticker, bid_volume, ask_volume, spread, mid_price,
                 order_imbalance, depth_imbalance, queue_velocity, liquidity_score, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (ts, ticker, bid_volume, ask_volume, spread, mid_price,
              order_imbalance, depth_imbalance, queue_velocity, liquidity_score,
              encrypted_raw))
        row = self._conn.execute("SELECT MAX(snapshot_id) FROM market_microstructure").fetchone()
        return row[0] if row else 0

    def record_feature(
        self, ticker: str, feature_name: str, feature_value: float
    ) -> None:
        ts = time.time()
        self._conn.execute("""
            INSERT INTO features_computed (timestamp, ticker, feature_name, feature_value)
            VALUES (?, ?, ?, ?)
        """, (ts, ticker, feature_name, feature_value))

    def record_calibration(
        self,
        ticker: str = "",
        model_version: str = "",
        raw_brier: float = 0.0,
        calibrated_brier: float = 0.0,
        brier_improvement: float = 0.0,
        n_samples: int = 0,
        fusion_mode: str = "",
    ) -> None:
        ts = time.time()
        self._conn.execute("""
            INSERT INTO calibration_metrics
                (timestamp, ticker, model_version, raw_brier, calibrated_brier,
                 brier_improvement, n_samples, fusion_mode)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (ts, ticker, model_version, raw_brier, calibrated_brier,
              brier_improvement, n_samples, fusion_mode))

    def record_signal(
        self,
        source: str,
        ticker: Optional[str],
        side: Optional[str],
        price: float,
        size: float,
        confidence: float,
        raw_text: str = "",
        regime_label: str = "",
        decision_json: Optional[dict] = None,
    ) -> int:
        from utils.security_utils import encrypt_data
        ts = time.time()
        encrypted_text = encrypt_data(raw_text) if raw_text else ""
        encrypted_decision = encrypt_data(json.dumps(decision_json)) if decision_json else None
        self._conn.execute("""
            INSERT INTO signals_ingested
                (timestamp, source, ticker, side, price, size, confidence, raw_text, regime_label, decision_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (ts, source, ticker, side, price, size, confidence, encrypted_text,
              regime_label, encrypted_decision))
        row = self._conn.execute("SELECT MAX(signal_id) FROM signals_ingested").fetchone()
        return row[0] if row else 0

    def record_decision(
        self,
        mode: str,
        ticker: str,
        side: str,
        price: float,
        sized: float,
        executed_size: float,
        kelly_pct: float = 0.0,
        regime_label: str = "",
        net_beta_pct: float = 0.0,
        authorized: bool = False,
        reason: str = "",
    ) -> None:
        from utils.security_utils import encrypt_data
        ts = time.time()
        encrypted_reason = encrypt_data(reason) if reason else ""
        self._conn.execute("""
            INSERT INTO decisions_log
                (timestamp, mode, ticker, side, price, sized, executed_size,
                 kelly_pct, regime_label, net_beta_pct, authorized, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (ts, mode, ticker, side, price, sized, executed_size,
              kelly_pct, regime_label, net_beta_pct, authorized, encrypted_reason))

    def set_replay_cursor(self, last_timestamp: float, last_signal_id: int = 0) -> None:
        self._conn.execute("""
            INSERT OR REPLACE INTO replay_cursor (id, last_timestamp, last_signal_id, mode)
            VALUES (1, ?, ?, 'REPLAY')
        """, (last_timestamp, last_signal_id))
        self._conn.commit()

    def get_replay_cursor(self) -> dict:
        row = self._conn.execute(
            "SELECT last_timestamp, last_signal_id, mode FROM replay_cursor WHERE id = 1"
        ).fetchone()
        if row:
            return {"last_timestamp": row[0], "last_signal_id": row[1], "mode": row[2]}
        return {"last_timestamp": 0.0, "last_signal_id": 0, "mode": "REPLAY"}

    def replay_signals(self, since_timestamp: float = 0.0, limit: int = 100) -> list[dict]:
        rows = self._conn.execute("""
            SELECT * FROM signals_ingested
            WHERE timestamp > ? AND source != 'replay_cursor'
            ORDER BY timestamp ASC
            LIMIT ?
        """, (since_timestamp, limit)).fetchall()
        columns = ["signal_id", "timestamp", "source", "ticker", "side",
                    "price", "size", "confidence", "raw_text", "regime_label", "decision_json"]
        return [dict(zip(columns, row)) for row in rows]

    def replay_decisions(self, since_timestamp: float = 0.0, limit: int = 100) -> list[dict]:
        rows = self._conn.execute("""
            SELECT * FROM decisions_log
            WHERE timestamp > ?
            ORDER BY timestamp ASC
            LIMIT ?
        """, (since_timestamp, limit)).fetchall()
        columns = ["decision_id", "timestamp", "mode", "ticker", "side",
                    "price", "sized", "executed_size", "kelly_pct",
                    "regime_label", "net_beta_pct", "authorized", "reason"]
        return [dict(zip(columns, row)) for row in rows]

    def get_microstructure_range(
        self, start_ts: float, end_ts: float, ticker: Optional[str] = None
    ) -> list[dict]:
        if ticker:
            rows = self._conn.execute("""
                SELECT * FROM market_microstructure
                WHERE timestamp >= ? AND timestamp <= ? AND ticker = ?
                ORDER BY timestamp ASC
            """, (start_ts, end_ts, ticker)).fetchall()
        else:
            rows = self._conn.execute("""
                SELECT * FROM market_microstructure
                WHERE timestamp >= ? AND timestamp <= ?
                ORDER BY timestamp ASC
            """, (start_ts, end_ts)).fetchall()
        columns = ["snapshot_id", "timestamp", "ticker", "bid_volume", "ask_volume",
                    "spread", "mid_price", "order_imbalance", "depth_imbalance",
                    "queue_velocity", "liquidity_score", "raw_json"]
        return [dict(zip(columns, row)) for row in rows]

    def get_feature_history(
        self, ticker: str, feature_name: str, since_ts: float = 0.0, limit: int = 1000
    ) -> list[dict]:
        rows = self._conn.execute("""
            SELECT timestamp, feature_value FROM features_computed
            WHERE ticker = ? AND feature_name = ? AND timestamp >= ?
            ORDER BY timestamp ASC
            LIMIT ?
        """, (ticker, feature_name, since_ts, limit)).fetchall()
        return [{"timestamp": r[0], "value": r[1]} for r in rows]

    def purge_before(self, cutoff_ts: float) -> int:
        total = 0
        for table in ["market_microstructure", "features_computed", "signals_ingested", "decisions_log"]:
            before = self._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            self._conn.execute(f"DELETE FROM {table} WHERE timestamp < ?", (cutoff_ts,))
            after = self._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            total += before - after
        self._conn.execute("CHECKPOINT")
        logger.info(f"Purged {total} rows before {datetime.fromtimestamp(cutoff_ts)}")
        return total

    def export_to_parquet(self, table: str, output_path: str, before_ts: float) -> int:
        count = self._conn.execute(f"""
            SELECT COUNT(*) FROM {table} WHERE timestamp < ?
        """, (before_ts,)).fetchone()[0]
        if count == 0:
            return 0
        self._conn.execute(f"""
            COPY (
                SELECT * FROM {table} WHERE timestamp < ?
            ) TO '{output_path}' (FORMAT 'PARQUET', COMPRESSION 'ZSTD')
        """, (before_ts,))
        logger.info(f"Exported {count} rows from {table} -> {output_path}")
        return count

    def get_stats(self) -> dict:
        stats = {}
        for table in ["market_microstructure", "features_computed", "signals_ingested", "decisions_log"]:
            row = self._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            stats[table] = row[0]
        return stats

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
