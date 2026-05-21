import json
import logging
import os
import time
from datetime import datetime
from typing import Any, Optional

from utils.exceptions import QuantFatal

logger = logging.getLogger("FeatureStore")


FEATURE_STORE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "user_data", "data", "feature_store.duckdb"
)


ALLOWED_TABLES = frozenset({
    "market_microstructure",
    "features_computed",
    "signals_ingested",
    "decisions_log",
    "web_events_raw",
})


class FeatureStore:
    def __init__(self, db_path: str = FEATURE_STORE_PATH) -> None:
        self.db_path = db_path
        self._conn: Any = None
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._connect()
        self._init_schema()

    @staticmethod
    def _validate_table(table: str) -> str:
        if table not in ALLOWED_TABLES:
            raise ValueError(f"Unsupported table: {table}")
        return table

    def _connect(self) -> None:
        try:
            import duckdb
            try:
                self._conn = duckdb.connect(self.db_path)
            except duckdb.IOException as e:
                if "lock" in str(e).lower():
                    logger.warning(f"⚠️ DuckDB lock conflict on {self.db_path}. Falling back to in-memory database (:memory:) to prevent crashes...")
                    self._conn = duckdb.connect(":memory:")
                else:
                    raise
            self._conn.execute("SET memory_limit = '2GB'")
            self._conn.execute("SET temp_directory = '/tmp/duckdb_tmp'")
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
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS web_events_raw (
                event_id INTEGER PRIMARY KEY DEFAULT nextval('seq_snapshot'),
                timestamp DOUBLE NOT NULL,
                source VARCHAR NOT NULL,
                event_type VARCHAR NOT NULL,
                market_slug VARCHAR,
                condition_id VARCHAR,
                raw_json VARCHAR NOT NULL
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
        self,
        ticker: str,
        feature_name: str,
        feature_value: float,
        timestamp: Optional[float] = None,
    ) -> None:
        ts = time.time() if timestamp is None else float(timestamp)
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

    def record_web_event(
        self,
        source: str,
        event_type: str,
        payload: dict,
        market_slug: str = "",
        condition_id: str = "",
        timestamp: Optional[float] = None,
    ) -> int:
        ts = time.time() if timestamp is None else float(timestamp)
        self._conn.execute("""
            INSERT INTO web_events_raw
                (timestamp, source, event_type, market_slug, condition_id, raw_json)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            ts,
            source,
            event_type,
            market_slug or str(payload.get("slug", "")),
            condition_id or str(payload.get("condition_id", payload.get("conditionId", ""))),
            json.dumps(payload, sort_keys=True),
        ))
        row = self._conn.execute("SELECT MAX(event_id) FROM web_events_raw").fetchone()
        return row[0] if row else 0

    def get_web_events(
        self,
        since_ts: float = 0.0,
        limit: int = 100,
        event_type: Optional[str] = None,
    ) -> list[dict]:
        if event_type:
            rows = self._conn.execute("""
                SELECT timestamp, source, event_type, market_slug, condition_id, raw_json
                FROM web_events_raw
                WHERE timestamp >= ? AND event_type = ?
                ORDER BY timestamp ASC
                LIMIT ?
            """, (since_ts, event_type, limit)).fetchall()
        else:
            rows = self._conn.execute("""
                SELECT timestamp, source, event_type, market_slug, condition_id, raw_json
                FROM web_events_raw
                WHERE timestamp >= ?
                ORDER BY timestamp ASC
                LIMIT ?
            """, (since_ts, limit)).fetchall()
        return [
            {
                "timestamp": r[0],
                "source": r[1],
                "event_type": r[2],
                "market_slug": r[3],
                "condition_id": r[4],
                "raw": json.loads(r[5]),
            }
            for r in rows
        ]

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
        self,
        ticker: str,
        feature_name: str,
        since_ts: float = 0.0,
        limit: int = 1000,
        until_ts: Optional[float] = None,
    ) -> list[dict]:
        if until_ts is None:
            rows = self._conn.execute("""
                SELECT timestamp, feature_value FROM features_computed
                WHERE ticker = ? AND feature_name = ? AND timestamp >= ?
                ORDER BY timestamp ASC
                LIMIT ?
            """, (ticker, feature_name, since_ts, limit)).fetchall()
        else:
            rows = self._conn.execute("""
                SELECT timestamp, feature_value FROM features_computed
                WHERE ticker = ? AND feature_name = ? AND timestamp >= ? AND timestamp <= ?
                ORDER BY timestamp ASC
                LIMIT ?
            """, (ticker, feature_name, since_ts, float(until_ts), limit)).fetchall()
        return [{"timestamp": r[0], "value": r[1]} for r in rows]

    def get_multi_market_feature_frame(
        self,
        target_ticker: str,
        base_feature_names: list[str],
        binance_symbol: Optional[str] = None,
        since_ts: float = 0.0,
        limit: int = 5000,
        window_seconds: int = 300,
    ) -> list[dict]:
        """
        Build a point-in-time aligned feature frame from target_ticker features
        and optional Binance-derived live features.

        The alignment uses as-of semantics by taking the last Binance feature
        observation at or before each target timestamp, then augments that row
        with rolling Binance summaries computed from web_events_raw.
        """
        target_rows = {
            name: self.get_feature_history(target_ticker, name, since_ts=since_ts, limit=limit)
            for name in base_feature_names
        }
        if not target_rows:
            return []

        timestamps = sorted(
            {
                float(row["timestamp"])
                for rows in target_rows.values()
                for row in rows
                if row and row.get("timestamp") is not None
            }
        )
        if not timestamps:
            return []

        binance_symbol = (binance_symbol or target_ticker).upper()
        binance_rows = self._conn.execute("""
            SELECT timestamp, raw_json
            FROM web_events_raw
            WHERE source = 'binance_ws'
              AND market_slug = ?
              AND timestamp >= ?
            ORDER BY timestamp ASC
            LIMIT ?
        """, (binance_symbol, since_ts, limit)).fetchall()

        parsed_binance = []
        for ts, raw_json in binance_rows:
            try:
                payload = json.loads(raw_json)
            except Exception:
                continue
            parsed_binance.append((float(ts), payload))

        out: list[dict] = []
        for ts in timestamps:
            row = {"timestamp": ts, "ticker": target_ticker}
            complete = True
            for name, history in target_rows.items():
                value = self._asof_value(history, ts)
                if value is None:
                    complete = False
                    break
                row[name] = value
            if not complete:
                continue

            if parsed_binance:
                row.update(
                    self._compute_binance_window_features(
                        parsed_binance,
                        ts,
                        window_seconds=window_seconds,
                    )
                )
            out.append(row)
        return out

    def prune_before(self, cutoff_ts: float, tables: Optional[list[str]] = None) -> dict[str, int]:
        """
        Delete rows older than cutoff_ts from append-only tables and checkpoint.

        This keeps high-frequency storage bounded while preserving recent raw
        ticks for live inference.
        """
        tables = tables or [
            "market_microstructure",
            "features_computed",
            "signals_ingested",
            "decisions_log",
            "web_events_raw",
        ]
        removed: dict[str, int] = {}
        for table in tables:
            t = self._validate_table(table)
            before = self._conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            self._conn.execute(f"DELETE FROM {t} WHERE timestamp < ?", (float(cutoff_ts),))
            after = self._conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            removed[table] = int(before - after)
        self._conn.commit()
        try:
            self._conn.execute("CHECKPOINT")
        except Exception:
            pass
        return removed

    def vacuum(self) -> None:
        try:
            self._conn.execute("VACUUM")
            self._conn.execute("CHECKPOINT")
        except Exception as exc:
            logger.debug("DuckDB vacuum skipped: %s", exc)

    @staticmethod
    def _asof_value(history: list[dict], ts: float) -> Optional[float]:
        last_value: Optional[float] = None
        for row in history:
            try:
                row_ts = float(row["timestamp"])
                value = float(row["value"])
            except (KeyError, TypeError, ValueError):
                continue
            if row_ts <= ts:
                last_value = value
            else:
                break
        return last_value

    @staticmethod
    def _compute_binance_window_features(
        parsed_binance: list[tuple[float, dict]],
        ts: float,
        window_seconds: int = 300,
    ) -> dict[str, float]:
        window_start = ts - float(window_seconds)
        window = [payload for event_ts, payload in parsed_binance if window_start <= event_ts <= ts]
        if not window:
            return {
                "binance_return_1m": 0.0,
                "binance_return_5m": 0.0,
                "binance_order_imbalance": 0.5,
                "binance_spread_bps": 0.0,
                "polymarket_spread_premium": 0.0,
            }

        mids = []
        spreads = []
        imbalances = []
        for payload in window:
            mid = float(payload.get("mid_price", 0.0) or 0.0)
            spread_bps = float(payload.get("spread_bps", 0.0) or 0.0)
            obi = float(payload.get("order_imbalance", 0.5) or 0.5)
            if mid > 0:
                mids.append(mid)
            spreads.append(spread_bps)
            imbalances.append(obi)

        if len(mids) >= 2:
            ret_1m = (mids[-1] - mids[0]) / mids[0] if mids[0] else 0.0
        else:
            ret_1m = 0.0

        if len(mids) >= 5:
            ret_5m = (mids[-1] - mids[0]) / mids[0] if mids[0] else 0.0
        else:
            ret_5m = ret_1m

        avg_spread_bps = sum(spreads) / len(spreads) if spreads else 0.0
        avg_obi = sum(imbalances) / len(imbalances) if imbalances else 0.5
        premium = abs(mids[-1] - mids[0]) / mids[0] if len(mids) >= 2 and mids[0] else 0.0

        return {
            "binance_return_1m": float(ret_1m),
            "binance_return_5m": float(ret_5m),
            "binance_order_imbalance": float(avg_obi),
            "binance_spread_bps": float(avg_spread_bps),
            "polymarket_spread_premium": float(premium),
        }

    def purge_before(self, cutoff_ts: float) -> int:
        total = 0
        for table in ["market_microstructure", "features_computed", "signals_ingested", "decisions_log", "web_events_raw"]:
            t = self._validate_table(table)
            before = self._conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            self._conn.execute(f"DELETE FROM {t} WHERE timestamp < ?", (cutoff_ts,))
            after = self._conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            total += before - after
        self._conn.execute("CHECKPOINT")
        logger.info(f"Purged {total} rows before {datetime.fromtimestamp(cutoff_ts)}")
        return total

    def export_to_parquet(self, table: str, output_path: str, before_ts: float) -> int:
        t = self._validate_table(table)
        count = self._conn.execute(f"""
            SELECT COUNT(*) FROM {t} WHERE timestamp < ?
        """, (before_ts,)).fetchone()[0]
        if count == 0:
            return 0
        self._conn.execute(f"""
            COPY (
                SELECT * FROM {t} WHERE timestamp < ?
            ) TO '{output_path}' (FORMAT 'PARQUET', COMPRESSION 'ZSTD')
        """, (before_ts,))
        logger.info(f"Exported {count} rows from {table} -> {output_path}")
        return count

    def get_stats(self) -> dict:
        stats = {}
        for table in ["market_microstructure", "features_computed", "signals_ingested", "decisions_log", "web_events_raw"]:
            t = self._validate_table(table)
            row = self._conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()
            stats[table] = row[0]
        return stats

    def get_latest_timestamp(self, table: str) -> Optional[float]:
        allowed_tables = {
            "market_microstructure",
            "features_computed",
            "signals_ingested",
            "decisions_log",
            "web_events_raw",
        }
        if table not in allowed_tables:
            raise ValueError(f"Unsupported table for latest timestamp lookup: {table}")

        row = self._conn.execute(f"SELECT MAX(timestamp) FROM {self._validate_table(table)}").fetchone()
        if not row or row[0] is None:
            return None
        return float(row[0])

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
