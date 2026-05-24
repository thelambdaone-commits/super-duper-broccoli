from __future__ import annotations

import asyncio
import csv
import importlib.util
import json
import math
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
from dotenv import load_dotenv

if __package__ in {None, ""}:
    _HELPER_PATH = Path(__file__).resolve().parents[1] / "_script_helpers.py"
    _SPEC = importlib.util.spec_from_file_location("_script_helpers", _HELPER_PATH)
    if _SPEC is None or _SPEC.loader is None:
        raise RuntimeError(f"Unable to load script helper from {_HELPER_PATH}")
    _HELPER = importlib.util.module_from_spec(_SPEC)
    _SPEC.loader.exec_module(_HELPER)
    ensure_repo_root = _HELPER.ensure_repo_root
else:
    from backtests._script_helpers import ensure_repo_root

ensure_repo_root(__file__)

from prediction_market_extensions._runtime_log import loader_event_sinks  # noqa: E402
from prediction_market_extensions.adapters.polymarket.loaders import (  # noqa: E402
    PolymarketDataLoader,
)
from prediction_market_extensions.adapters.prediction_market.backtest_utils import (  # noqa: E402
    infer_realized_outcome_from_metadata,
)


ARTIFACT_ROOT = Path("output/telonex_churn/model_research")
_RESOLVED_UP_CACHE_PATH = ARTIFACT_ROOT / "telonex_btc_5m_resolved_up_cache.json"
_RESOLVED_UP_CACHE: dict[str, float | None] | None = None
_RESOLVED_UP_DIRTY = 0
_LOCAL_GAMMA_RESOLVED_UP_CACHE: dict[str, float] | None = None
_WINDOW_SECONDS = 300
_DEFAULT_START_TS = 1_777_258_800  # 2026-04-27T03:00:00Z
_DEFAULT_WINDOWS = 288
_DEFAULT_SNAPSHOT_SECONDS = (240, 180, 120, 60, 30, 10)
_SPOT_ROOT = Path.home() / ".cache/nautilus_trader/telonex-binance/raw/binance"
_FEATURE_COLUMNS = (
    "seconds_left",
    "price_diff",
    "return_since_start",
    "momentum_15s",
    "momentum_30s",
    "momentum_60s",
    "volatility_60s",
    "volume_60s",
    "btc_book_mid",
    "btc_book_spread_bps",
    "btc_book_bid_size",
    "btc_book_ask_size",
    "btc_book_bid_depth",
    "btc_book_ask_depth",
    "btc_book_imbalance",
    "btc_book_microprice_diff",
    "btc_trade_book_diff",
    "btc_book_age_seconds",
    "yes_mid",
    "yes_spread",
    "yes_bid_size",
    "yes_ask_size",
    "yes_book_imbalance",
    "yes_microprice",
    "no_mid",
    "no_spread",
    "no_bid_size",
    "no_ask_size",
    "no_book_imbalance",
    "no_microprice",
    "yes_no_ask_cost",
)
_EXTRA_SPOT_FEATURE_SUFFIXES = (
    "return_since_start",
    "momentum_15s_bps",
    "momentum_30s_bps",
    "momentum_60s_bps",
    "volatility_60s_bps",
    "volume_60s",
    "book_spread_bps",
    "book_bid_size",
    "book_ask_size",
    "book_bid_depth",
    "book_ask_depth",
    "book_imbalance",
    "book_microprice_diff_bps",
    "trade_book_diff_bps",
    "book_age_seconds",
)
_SPOT_QUOTE_FEATURE_SUFFIXES = (
    "quote_mid",
    "quote_spread_bps",
    "quote_bid_size",
    "quote_ask_size",
    "quote_imbalance",
    "quote_trade_diff_bps",
    "quote_book_mid_diff_bps",
    "quote_age_seconds",
)


@dataclass
class BtcFeatureStore:
    symbol: str
    start_ts: int
    end_ts: int
    prices: np.ndarray
    volumes: np.ndarray
    cumulative_volumes: np.ndarray
    book_depth_levels: int = 5
    book_max_age_seconds: int = 8
    _book_cache: dict[int, dict[str, float] | None] = field(default_factory=dict)

    def _offset(self, ts: int) -> int:
        return int(ts) - self.start_ts

    def price_at(self, ts: int) -> float:
        offset = self._offset(ts)
        if offset < 0 or offset >= len(self.prices):
            return math.nan
        return float(self.prices[offset])

    def momentum(self, ts: int, seconds: int) -> float:
        current = self.price_at(ts)
        prior = self.price_at(ts - seconds)
        if not math.isfinite(current) or not math.isfinite(prior):
            return math.nan
        return current - prior

    def volume(self, ts: int, seconds: int) -> float:
        end = min(max(self._offset(ts) + 1, 0), len(self.cumulative_volumes) - 1)
        start = min(max(self._offset(ts - seconds) + 1, 0), len(self.cumulative_volumes) - 1)
        return float(self.cumulative_volumes[end] - self.cumulative_volumes[start])

    def volatility(self, ts: int, seconds: int) -> float:
        end = self._offset(ts)
        start = max(0, end - seconds)
        if end <= start + 2:
            return math.nan
        window = self.prices[start : end + 1]
        if not np.all(np.isfinite(window)):
            return math.nan
        returns = np.diff(window)
        if returns.size <= 1:
            return 0.0
        return float(np.std(returns))

    def book_features_at(self, ts: int) -> dict[str, float] | None:
        ts = int(ts)
        if ts in self._book_cache:
            cached = self._book_cache[ts]
            return dict(cached) if cached is not None else None
        path = _spot_book_snapshot_path(
            self.symbol,
            datetime.fromtimestamp(ts, UTC).date().isoformat(),
        )
        if path is None:
            self._book_cache[ts] = None
            return None
        conn = duckdb.connect(":memory:")
        try:
            rows = conn.execute(
                """
                SELECT *
                FROM read_parquet(?)
                WHERE timestamp_us BETWEEN ? AND ?
                  AND timestamp_us <= ?
                ORDER BY timestamp_us DESC
                LIMIT 1
                """,
                [
                    str(path),
                    (ts - self.book_max_age_seconds) * 1_000_000,
                    ts * 1_000_000,
                    ts * 1_000_000,
                ],
            ).fetchall()
            names = [item[0] for item in conn.description or []]
        finally:
            conn.close()
        if not rows:
            self._book_cache[ts] = None
            return None
        row = dict(zip(names, rows[0], strict=True))
        features = _btc_book_features(row, levels=self.book_depth_levels, target_ts=ts)
        self._book_cache[ts] = dict(features) if features is not None else None
        return features


@dataclass(frozen=True)
class LogisticModel:
    columns: tuple[str, ...]
    means: tuple[float, ...]
    scales: tuple[float, ...]
    weights: tuple[float, ...]
    bias: float


@dataclass(frozen=True)
class Policy:
    edge: float
    seconds_left: tuple[int, ...]

    @property
    def name(self) -> str:
        buckets = "_".join(str(value) for value in self.seconds_left)
        return f"edge_{self.edge:.2f}_seconds_{buckets}"


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _run_label() -> str:
    raw = os.getenv("TELONEX_CHURN_BTC_MODEL_RUN_LABEL", "s138_snapshot_model")
    label = "".join(
        character if character.isalnum() or character in {"_", "-"} else "_"
        for character in raw.strip()
    ).strip("_")
    return label or "s138_snapshot_model"


def _normalize_spot_symbol(symbol: str) -> str:
    normalized = symbol.strip().lower()
    if not normalized:
        raise ValueError("Spot symbol must not be empty.")
    return normalized


def _extra_spot_symbols() -> tuple[str, ...]:
    raw = os.getenv("TELONEX_CHURN_BTC_MODEL_EXTRA_SPOT_SYMBOLS", "")
    values: list[str] = []
    seen: set[str] = {"btcusdt"}
    for item in raw.split(","):
        symbol = item.strip()
        if not symbol:
            continue
        normalized = _normalize_spot_symbol(symbol)
        if normalized in seen:
            continue
        seen.add(normalized)
        values.append(normalized)
    return tuple(values)


def _spot_feature_prefix(symbol: str) -> str:
    normalized = _normalize_spot_symbol(symbol)
    if normalized.endswith("usdt"):
        normalized = normalized[:-4]
    return "".join(character if character.isalnum() else "_" for character in normalized)


def _extra_spot_feature_columns(symbols: tuple[str, ...]) -> tuple[str, ...]:
    columns: list[str] = []
    for symbol in symbols:
        prefix = _spot_feature_prefix(symbol)
        columns.extend(f"{prefix}_{suffix}" for suffix in _EXTRA_SPOT_FEATURE_SUFFIXES)
    return tuple(columns)


def _spot_quote_feature_columns(symbols: tuple[str, ...]) -> tuple[str, ...]:
    columns: list[str] = []
    for symbol in symbols:
        prefix = _spot_feature_prefix(symbol)
        columns.extend(f"{prefix}_{suffix}" for suffix in _SPOT_QUOTE_FEATURE_SUFFIXES)
    return tuple(columns)


def _feature_columns(
    extra_spot_symbols: tuple[str, ...] | None = None,
    *,
    use_spot_quotes: bool | None = None,
) -> tuple[str, ...]:
    symbols = _extra_spot_symbols() if extra_spot_symbols is None else extra_spot_symbols
    include_quotes = (
        _env_bool("TELONEX_CHURN_BTC_MODEL_USE_SPOT_QUOTES")
        if use_spot_quotes is None
        else use_spot_quotes
    )
    quote_symbols = ("btcusdt", *symbols) if include_quotes else ()
    return (
        *_FEATURE_COLUMNS,
        *_extra_spot_feature_columns(symbols),
        *_spot_quote_feature_columns(quote_symbols),
    )


def _date_strings(start_ts: int, end_ts: int) -> list[str]:
    start = datetime.fromtimestamp(start_ts, UTC).date()
    end = datetime.fromtimestamp(end_ts, UTC).date()
    days = (end - start).days
    return [(start + timedelta(days=offset)).isoformat() for offset in range(days + 1)]


def _spot_trade_paths(symbol: str, start_ts: int, end_ts: int) -> list[str]:
    root = _SPOT_ROOT / _normalize_spot_symbol(symbol) / "trades"
    return [
        str(path)
        for date in _date_strings(start_ts, end_ts)
        for path in (root / f"{date}.parquet",)
        if path.exists()
    ]


def _btc_trade_paths(start_ts: int, end_ts: int) -> list[str]:
    return _spot_trade_paths("btcusdt", start_ts, end_ts)


def _spot_quote_path(symbol: str, date: str) -> Path | None:
    path = _SPOT_ROOT / _normalize_spot_symbol(symbol) / "quotes" / f"{date}.parquet"
    return path if path.exists() else None


def _spot_book_snapshot_path(symbol: str, date: str) -> Path | None:
    path = _SPOT_ROOT / _normalize_spot_symbol(symbol) / "book_snapshot_25" / f"{date}.parquet"
    return path if path.exists() else None


def _btc_book_snapshot_path(date: str) -> Path | None:
    return _spot_book_snapshot_path("btcusdt", date)


def _spot_book_paths(symbol: str, start_ts: int, end_ts: int) -> list[str]:
    return [
        str(path)
        for date in _date_strings(start_ts, end_ts)
        for path in (
            _SPOT_ROOT / _normalize_spot_symbol(symbol) / "book_snapshot_25" / f"{date}.parquet",
        )
        if path.exists()
    ]


def _btc_book_paths(start_ts: int, end_ts: int) -> list[str]:
    return _spot_book_paths("btcusdt", start_ts, end_ts)


def _book_snapshot_path(slug: str, outcome: str, date: str) -> Path | None:
    root = Path.home() / ".cache/nautilus_trader/telonex/api-days"
    pattern = f"*/polymarket/book_snapshot_full/{slug}/outcome={outcome}/{date}.parquet"
    paths = sorted(root.glob(pattern))
    if not paths:
        return None
    return paths[-1]


def _load_spot_features(
    symbol: str,
    start_ts: int,
    end_ts: int,
    *,
    book_depth_levels: int = 5,
    book_max_age_seconds: int = 8,
) -> BtcFeatureStore:
    symbol = _normalize_spot_symbol(symbol)
    feature_start = start_ts - 180
    feature_end = end_ts + 60
    paths = _spot_trade_paths(symbol, feature_start, feature_end)
    if not paths:
        raise FileNotFoundError(
            f"No Telonex Binance {symbol.upper()} trade parquet files found for "
            f"{feature_start=} {feature_end=}."
        )

    conn = duckdb.connect(":memory:")
    rows = conn.execute(
        """
        SELECT
            CAST(floor(timestamp_us / 1000000) AS BIGINT) AS ts,
            arg_max(CAST(price AS DOUBLE), timestamp_us) AS close,
            sum(CAST(size AS DOUBLE)) AS volume
        FROM read_parquet(?)
        WHERE timestamp_us BETWEEN ? AND ?
        GROUP BY ts
        ORDER BY ts
        """,
        [paths, feature_start * 1_000_000, feature_end * 1_000_000],
    ).fetchall()
    conn.close()
    if not rows:
        raise RuntimeError(f"Telonex Binance {symbol.upper()} trade query returned no rows.")

    seconds = np.arange(feature_start, feature_end + 1, dtype=np.int64)
    source_seconds = np.array([int(row[0]) for row in rows], dtype=np.int64)
    source_prices = np.array([float(row[1]) for row in rows], dtype=np.float64)
    source_volumes = np.array([float(row[2] or 0.0) for row in rows], dtype=np.float64)
    indexes = np.searchsorted(source_seconds, seconds, side="right") - 1
    prices = np.full(seconds.shape, np.nan, dtype=np.float64)
    valid = indexes >= 0
    prices[valid] = source_prices[indexes[valid]]
    volumes = np.zeros(seconds.shape, dtype=np.float64)
    exact_indexes = np.searchsorted(seconds, source_seconds)
    in_range = (exact_indexes >= 0) & (exact_indexes < len(seconds))
    volumes[exact_indexes[in_range]] = source_volumes[in_range]
    cumulative_volumes = np.concatenate(([0.0], np.cumsum(volumes)))
    return BtcFeatureStore(
        symbol=symbol,
        start_ts=feature_start,
        end_ts=feature_end,
        prices=prices,
        volumes=volumes,
        cumulative_volumes=cumulative_volumes,
        book_depth_levels=book_depth_levels,
        book_max_age_seconds=book_max_age_seconds,
    )


def _load_btc_features(
    start_ts: int,
    end_ts: int,
    *,
    book_depth_levels: int = 5,
    book_max_age_seconds: int = 8,
) -> BtcFeatureStore:
    return _load_spot_features(
        "btcusdt",
        start_ts,
        end_ts,
        book_depth_levels=book_depth_levels,
        book_max_age_seconds=book_max_age_seconds,
    )


def _level_from_row(row: dict[str, Any], *, side: str, index: int) -> tuple[float, float] | None:
    try:
        price = float(row[f"{side}_price_{index}"])
        size = float(row[f"{side}_size_{index}"])
    except (KeyError, TypeError, ValueError):
        return None
    if not math.isfinite(price) or not math.isfinite(size) or price <= 0.0 or size <= 0.0:
        return None
    return price, size


def _spot_book_features(
    row: dict[str, Any],
    *,
    levels: int,
    target_ts: int,
    prefix: str,
) -> dict[str, float] | None:
    bids = [
        level
        for index in range(max(1, int(levels)))
        if (level := _level_from_row(row, side="bid", index=index)) is not None
    ]
    asks = [
        level
        for index in range(max(1, int(levels)))
        if (level := _level_from_row(row, side="ask", index=index)) is not None
    ]
    if not bids or not asks:
        return None
    bid, bid_size = bids[0]
    ask, ask_size = asks[0]
    if bid >= ask:
        return None
    bid_depth = sum(size for _, size in bids)
    ask_depth = sum(size for _, size in asks)
    depth_total = bid_depth + ask_depth
    size_total = bid_size + ask_size
    if depth_total <= 0.0 or size_total <= 0.0:
        return None
    mid = (bid + ask) / 2.0
    spread = ask - bid
    microprice = ((ask * bid_size) + (bid * ask_size)) / size_total
    timestamp_us = int(row.get("timestamp_us") or 0)
    return {
        f"{prefix}_book_mid": mid,
        f"{prefix}_book_spread": spread,
        f"{prefix}_book_spread_bps": (spread / mid) * 10_000.0,
        f"{prefix}_book_bid_size": bid_size,
        f"{prefix}_book_ask_size": ask_size,
        f"{prefix}_book_bid_depth": bid_depth,
        f"{prefix}_book_ask_depth": ask_depth,
        f"{prefix}_book_imbalance": (bid_depth - ask_depth) / depth_total,
        f"{prefix}_book_microprice": microprice,
        f"{prefix}_book_microprice_diff": microprice - mid,
        f"{prefix}_book_age_seconds": (target_ts * 1_000_000 - timestamp_us) / 1_000_000.0,
    }


def _spot_quote_features(
    row: dict[str, Any],
    *,
    target_ts: int,
    prefix: str,
) -> dict[str, float] | None:
    try:
        bid = float(row["bid_price"])
        ask = float(row["ask_price"])
        bid_size = float(row["bid_size"])
        ask_size = float(row["ask_size"])
    except (KeyError, TypeError, ValueError):
        return None
    if (
        not math.isfinite(bid)
        or not math.isfinite(ask)
        or not math.isfinite(bid_size)
        or not math.isfinite(ask_size)
        or bid <= 0.0
        or ask <= 0.0
        or bid >= ask
        or bid_size <= 0.0
        or ask_size <= 0.0
    ):
        return None
    size_total = bid_size + ask_size
    if size_total <= 0.0:
        return None
    mid = (bid + ask) / 2.0
    spread = ask - bid
    timestamp_us = int(row.get("timestamp_us") or 0)
    return {
        f"{prefix}_quote_mid": mid,
        f"{prefix}_quote_spread_bps": (spread / mid) * 10_000.0,
        f"{prefix}_quote_bid_size": bid_size,
        f"{prefix}_quote_ask_size": ask_size,
        f"{prefix}_quote_imbalance": (bid_size - ask_size) / size_total,
        f"{prefix}_quote_age_seconds": (target_ts * 1_000_000 - timestamp_us) / 1_000_000.0,
    }


def _btc_book_features(
    row: dict[str, Any],
    *,
    levels: int,
    target_ts: int,
) -> dict[str, float] | None:
    return _spot_book_features(row, levels=levels, target_ts=target_ts, prefix="btc")


def _load_spot_book_snapshots(
    symbol: str,
    *,
    starts: tuple[int, ...],
    snapshot_seconds: tuple[int, ...],
    max_age_seconds: int,
    depth_levels: int,
    prefix: str,
) -> dict[int, dict[str, float]]:
    targets_by_date: dict[str, list[int]] = {}
    for market_start_ts in starts:
        for seconds_left in snapshot_seconds:
            target_ts = market_start_ts + _WINDOW_SECONDS - int(seconds_left)
            date = datetime.fromtimestamp(target_ts, UTC).date().isoformat()
            targets_by_date.setdefault(date, []).append(target_ts)

    snapshots: dict[int, dict[str, float]] = {}
    conn = duckdb.connect(":memory:")
    try:
        for date, target_seconds in sorted(targets_by_date.items()):
            path = _spot_book_snapshot_path(symbol, date)
            if path is None:
                continue
            unique_targets = sorted(set(target_seconds))
            values_sql = ", ".join(
                f"({target_ts * 1_000_000}, {target_ts})" for target_ts in unique_targets
            )
            min_target = min(unique_targets) * 1_000_000
            max_target = max(unique_targets) * 1_000_000
            rows = conn.execute(
                f"""
                WITH targets(target_us, target_ts) AS (VALUES {values_sql}),
                snapshots AS (
                    SELECT *
                    FROM read_parquet(?)
                    WHERE timestamp_us BETWEEN ? AND ?
                )
                SELECT targets.target_ts, snapshots.*
                FROM targets
                ASOF LEFT JOIN snapshots
                    ON targets.target_us >= snapshots.timestamp_us
                ORDER BY targets.target_us
                """,
                [
                    str(path),
                    min_target - (max_age_seconds * 1_000_000),
                    max_target,
                ],
            ).fetchall()
            names = [item[0] for item in conn.description or []]
            for raw in rows:
                row = dict(zip(names, raw, strict=True))
                timestamp_us = row.get("timestamp_us")
                target_ts = row.get("target_ts")
                if timestamp_us is None or target_ts is None:
                    continue
                age_seconds = (int(target_ts) * 1_000_000 - int(timestamp_us)) / 1_000_000.0
                if age_seconds < 0.0 or age_seconds > max_age_seconds:
                    continue
                features = _spot_book_features(
                    row,
                    levels=depth_levels,
                    target_ts=int(target_ts),
                    prefix=prefix,
                )
                if features is not None:
                    snapshots[int(target_ts)] = features
    finally:
        conn.close()
    return snapshots


def _load_btc_book_snapshots(
    *,
    starts: tuple[int, ...],
    snapshot_seconds: tuple[int, ...],
    max_age_seconds: int,
    depth_levels: int,
) -> dict[int, dict[str, float]]:
    return _load_spot_book_snapshots(
        "btcusdt",
        starts=starts,
        snapshot_seconds=snapshot_seconds,
        max_age_seconds=max_age_seconds,
        depth_levels=depth_levels,
        prefix="btc",
    )


def _load_spot_quote_snapshots(
    symbol: str,
    *,
    starts: tuple[int, ...],
    snapshot_seconds: tuple[int, ...],
    max_age_seconds: int,
    prefix: str,
) -> dict[int, dict[str, float]]:
    targets_by_date: dict[str, list[int]] = {}
    for market_start_ts in starts:
        for seconds_left in snapshot_seconds:
            target_ts = market_start_ts + _WINDOW_SECONDS - int(seconds_left)
            date = datetime.fromtimestamp(target_ts, UTC).date().isoformat()
            targets_by_date.setdefault(date, []).append(target_ts)

    snapshots: dict[int, dict[str, float]] = {}
    conn = duckdb.connect(":memory:")
    try:
        for date, target_seconds in sorted(targets_by_date.items()):
            path = _spot_quote_path(symbol, date)
            if path is None:
                continue
            unique_targets = sorted(set(target_seconds))
            values_sql = ", ".join(
                f"({target_ts * 1_000_000}, {target_ts})" for target_ts in unique_targets
            )
            min_target = min(unique_targets) * 1_000_000
            max_target = max(unique_targets) * 1_000_000
            rows = conn.execute(
                f"""
                WITH targets(target_us, target_ts) AS (VALUES {values_sql}),
                quotes AS (
                    SELECT
                        timestamp_us,
                        CAST(bid_price AS DOUBLE) AS bid_price,
                        CAST(bid_size AS DOUBLE) AS bid_size,
                        CAST(ask_price AS DOUBLE) AS ask_price,
                        CAST(ask_size AS DOUBLE) AS ask_size
                    FROM read_parquet(?)
                    WHERE timestamp_us BETWEEN ? AND ?
                )
                SELECT targets.target_ts, quotes.*
                FROM targets
                ASOF LEFT JOIN quotes
                    ON targets.target_us >= quotes.timestamp_us
                ORDER BY targets.target_us
                """,
                [
                    str(path),
                    min_target - (max_age_seconds * 1_000_000),
                    max_target,
                ],
            ).fetchall()
            names = [item[0] for item in conn.description or []]
            for raw in rows:
                row = dict(zip(names, raw, strict=True))
                timestamp_us = row.get("timestamp_us")
                target_ts = row.get("target_ts")
                if timestamp_us is None or target_ts is None:
                    continue
                age_seconds = (int(target_ts) * 1_000_000 - int(timestamp_us)) / 1_000_000.0
                if age_seconds < 0.0 or age_seconds > max_age_seconds:
                    continue
                features = _spot_quote_features(
                    row,
                    target_ts=int(target_ts),
                    prefix=prefix,
                )
                if features is not None:
                    snapshots[int(target_ts)] = features
    finally:
        conn.close()
    return snapshots


def _coerce_level(level: object) -> tuple[float, float] | None:
    if not isinstance(level, dict):
        return None
    try:
        price = float(level["price"])
        size = float(level["size"])
    except (KeyError, TypeError, ValueError):
        return None
    if not math.isfinite(price) or not math.isfinite(size) or size <= 0.0:
        return None
    return price, size


def _book_features(bids: object, asks: object, *, levels: int) -> dict[str, float] | None:
    if not isinstance(bids, list) or not isinstance(asks, list):
        return None
    bid_levels = [level for item in bids if (level := _coerce_level(item)) is not None]
    ask_levels = [level for item in asks if (level := _coerce_level(item)) is not None]
    if not bid_levels or not ask_levels:
        return None
    bid_levels.sort(key=lambda item: item[0], reverse=True)
    ask_levels.sort(key=lambda item: item[0])
    bid_px, bid_size = bid_levels[0]
    ask_px, ask_size = ask_levels[0]
    if bid_px <= 0.0 or ask_px <= 0.0 or bid_px >= ask_px:
        return None
    bid_depth = sum(size for _, size in bid_levels[:levels])
    ask_depth = sum(size for _, size in ask_levels[:levels])
    depth_total = bid_depth + ask_depth
    size_total = bid_size + ask_size
    return {
        "bid": bid_px,
        "ask": ask_px,
        "mid": (bid_px + ask_px) / 2.0,
        "spread": ask_px - bid_px,
        "bid_size": bid_size,
        "ask_size": ask_size,
        "bid_depth": bid_depth,
        "ask_depth": ask_depth,
        "book_imbalance": (bid_depth - ask_depth) / depth_total if depth_total > 0.0 else 0.0,
        "microprice": (
            ((ask_px * bid_size) + (bid_px * ask_size)) / size_total
            if size_total > 0.0
            else (bid_px + ask_px) / 2.0
        ),
    }


def _snapshot_targets_by_date(
    market_start_ts: int, snapshot_seconds: tuple[int, ...]
) -> dict[str, list[tuple[int, int]]]:
    targets: dict[str, list[tuple[int, int]]] = {}
    for seconds_left in snapshot_seconds:
        target_ts = market_start_ts + _WINDOW_SECONDS - seconds_left
        date = datetime.fromtimestamp(target_ts, UTC).date().isoformat()
        targets.setdefault(date, []).append((seconds_left, target_ts * 1_000_000))
    return targets


def _query_book_snapshots(
    conn: duckdb.DuckDBPyConnection,
    path: Path,
    targets: list[tuple[int, int]],
    *,
    max_age_seconds: int,
    depth_levels: int,
) -> dict[int, dict[str, float]]:
    if not targets:
        return {}
    values_sql = ", ".join(f"({target_us}, {seconds_left})" for seconds_left, target_us in targets)
    min_target = min(target_us for _, target_us in targets)
    max_target = max(target_us for _, target_us in targets)
    rows = conn.execute(
        f"""
        WITH targets(target_us, seconds_left) AS (VALUES {values_sql}),
        snapshots AS (
            SELECT timestamp_us, bids, asks
            FROM read_parquet(?)
            WHERE timestamp_us BETWEEN ? AND ?
        )
        SELECT target_us, seconds_left, timestamp_us, bids, asks
        FROM targets
        ASOF LEFT JOIN snapshots
            ON targets.target_us >= snapshots.timestamp_us
        ORDER BY target_us
        """,
        [
            str(path),
            min_target - (max_age_seconds * 1_000_000),
            max_target,
        ],
    ).fetchall()
    snapshots: dict[int, dict[str, float]] = {}
    for target_us, seconds_left, timestamp_us, bids, asks in rows:
        if timestamp_us is None:
            continue
        age_seconds = (int(target_us) - int(timestamp_us)) / 1_000_000.0
        if age_seconds < 0.0 or age_seconds > max_age_seconds:
            continue
        features = _book_features(bids, asks, levels=depth_levels)
        if features is None:
            continue
        features["book_age_seconds"] = age_seconds
        features["book_timestamp_us"] = float(timestamp_us)
        snapshots[int(seconds_left)] = features
    return snapshots


def _market_snapshot_features(
    conn: duckdb.DuckDBPyConnection,
    *,
    slug: str,
    outcome: str,
    market_start_ts: int,
    snapshot_seconds: tuple[int, ...],
    max_age_seconds: int,
    depth_levels: int,
) -> dict[int, dict[str, float]]:
    snapshots: dict[int, dict[str, float]] = {}
    for date, targets in _snapshot_targets_by_date(market_start_ts, snapshot_seconds).items():
        path = _book_snapshot_path(slug, outcome, date)
        if path is None:
            continue
        snapshots.update(
            _query_book_snapshots(
                conn,
                path,
                targets,
                max_age_seconds=max_age_seconds,
                depth_levels=depth_levels,
            )
        )
    return snapshots


def _bps_return(current: float, prior: float) -> float:
    if not math.isfinite(current) or not math.isfinite(prior) or prior <= 0.0:
        return math.nan
    return ((current / prior) - 1.0) * 10_000.0


def _add_spot_quote_features(
    row: dict[str, Any],
    *,
    prefix: str,
    quote: dict[str, float],
    trade_price: float,
    book_mid: float,
) -> bool:
    quote_mid = float(quote.get(f"{prefix}_quote_mid", math.nan))
    if (
        not math.isfinite(quote_mid)
        or not math.isfinite(trade_price)
        or not math.isfinite(book_mid)
        or quote_mid <= 0.0
        or book_mid <= 0.0
    ):
        return False
    row.update(
        {
            f"{prefix}_quote_mid": quote_mid,
            f"{prefix}_quote_spread_bps": quote[f"{prefix}_quote_spread_bps"],
            f"{prefix}_quote_bid_size": quote[f"{prefix}_quote_bid_size"],
            f"{prefix}_quote_ask_size": quote[f"{prefix}_quote_ask_size"],
            f"{prefix}_quote_imbalance": quote[f"{prefix}_quote_imbalance"],
            f"{prefix}_quote_trade_diff_bps": ((trade_price - quote_mid) / quote_mid) * 10_000.0,
            f"{prefix}_quote_book_mid_diff_bps": ((quote_mid - book_mid) / book_mid) * 10_000.0,
            f"{prefix}_quote_age_seconds": quote[f"{prefix}_quote_age_seconds"],
        }
    )
    return True


def _add_extra_spot_features(
    row: dict[str, Any],
    *,
    prefix: str,
    store: BtcFeatureStore,
    books: dict[int, dict[str, float]],
    quote: dict[str, float] | None = None,
    market_start_ts: int,
    snapshot_ts: int,
    use_spot_quotes: bool = False,
) -> bool:
    start_price = store.price_at(market_start_ts)
    current_price = store.price_at(snapshot_ts)
    if not math.isfinite(start_price) or not math.isfinite(current_price):
        return False
    book = books.get(snapshot_ts)
    if book is None:
        return False
    book_mid = float(book.get(f"{prefix}_book_mid", math.nan))
    if not math.isfinite(book_mid) or book_mid <= 0.0:
        return False
    volatility_60s = store.volatility(snapshot_ts, 60)
    row.update(
        {
            f"{prefix}_return_since_start": (current_price / start_price) - 1.0,
            f"{prefix}_momentum_15s_bps": _bps_return(
                current_price, store.price_at(snapshot_ts - 15)
            ),
            f"{prefix}_momentum_30s_bps": _bps_return(
                current_price, store.price_at(snapshot_ts - 30)
            ),
            f"{prefix}_momentum_60s_bps": _bps_return(
                current_price, store.price_at(snapshot_ts - 60)
            ),
            f"{prefix}_volatility_60s_bps": (
                (volatility_60s / current_price) * 10_000.0
                if math.isfinite(volatility_60s) and current_price > 0.0
                else math.nan
            ),
            f"{prefix}_volume_60s": store.volume(snapshot_ts, 60),
            f"{prefix}_book_spread_bps": book[f"{prefix}_book_spread_bps"],
            f"{prefix}_book_bid_size": book[f"{prefix}_book_bid_size"],
            f"{prefix}_book_ask_size": book[f"{prefix}_book_ask_size"],
            f"{prefix}_book_bid_depth": book[f"{prefix}_book_bid_depth"],
            f"{prefix}_book_ask_depth": book[f"{prefix}_book_ask_depth"],
            f"{prefix}_book_imbalance": book[f"{prefix}_book_imbalance"],
            f"{prefix}_book_microprice_diff_bps": (
                float(book[f"{prefix}_book_microprice_diff"]) / book_mid
            )
            * 10_000.0,
            f"{prefix}_trade_book_diff_bps": ((current_price - book_mid) / book_mid) * 10_000.0,
            f"{prefix}_book_age_seconds": book[f"{prefix}_book_age_seconds"],
        }
    )
    if use_spot_quotes:
        if quote is None or not _add_spot_quote_features(
            row,
            prefix=prefix,
            quote=quote,
            trade_price=current_price,
            book_mid=book_mid,
        ):
            return False
    return True


async def _resolved_up(slug: str) -> float | None:
    global _RESOLVED_UP_DIRTY
    cache = _resolved_up_cache()
    if slug in cache:
        return cache[slug]

    for attempt in range(5):
        try:
            with loader_event_sinks([]):
                loader = await PolymarketDataLoader.from_market_slug(slug, token_index=0)
            outcome = infer_realized_outcome_from_metadata(
                loader.resolution_metadata,
                loader.instrument.outcome,
            )
            value = None if outcome is None else float(outcome)
            cache[slug] = value
            _RESOLVED_UP_DIRTY += 1
            if _RESOLVED_UP_DIRTY >= 100:
                _flush_resolved_up_cache()
            return value
        except ValueError:
            cache[slug] = None
            _RESOLVED_UP_DIRTY += 1
            if _RESOLVED_UP_DIRTY >= 100:
                _flush_resolved_up_cache()
            return None
        except Exception as exc:
            if attempt >= 4:
                print(f"label lookup failed slug={slug} error={exc!r}", flush=True)
                return None
            await asyncio.sleep(min(20.0, 2.0**attempt))
    return None


def _spot_resolved_up(btc: BtcFeatureStore, market_start_ts: int) -> float | None:
    start_price = btc.price_at(market_start_ts)
    end_price = btc.price_at(market_start_ts + _WINDOW_SECONDS)
    if not math.isfinite(start_price) or not math.isfinite(end_price):
        return None
    return 1.0 if end_price >= start_price else 0.0


async def _resolved_up_labels(
    starts: tuple[int, ...],
    *,
    btc: BtcFeatureStore | None = None,
) -> dict[int, float | None]:
    resolved_cache = _resolved_up_cache()
    local_gamma = _local_gamma_resolved_up_cache()
    allow_network = _env_bool("TELONEX_CHURN_BTC_MODEL_LABEL_ALLOW_NETWORK", True)
    use_spot_fallback = _env_bool("TELONEX_CHURN_BTC_MODEL_LABEL_FALLBACK_SPOT")
    labels: dict[int, float | None] = {}
    missing: list[int] = []
    source_counts = {
        "resolved_cache": 0,
        "local_gamma": 0,
        "spot_fallback": 0,
        "missing": 0,
    }
    for market_start_ts in starts:
        slug = _market_slug(market_start_ts)
        if slug in resolved_cache and resolved_cache[slug] is not None:
            labels[market_start_ts] = resolved_cache[slug]
            source_counts["resolved_cache"] += 1
            continue
        if slug in local_gamma:
            labels[market_start_ts] = local_gamma[slug]
            source_counts["local_gamma"] += 1
            continue
        if use_spot_fallback and btc is not None:
            resolved = _spot_resolved_up(btc, market_start_ts)
            if resolved is not None:
                labels[market_start_ts] = resolved
                source_counts["spot_fallback"] += 1
                continue
        if allow_network:
            missing.append(market_start_ts)
        else:
            labels[market_start_ts] = None
            source_counts["missing"] += 1

    print(
        "label cache: "
        + " ".join(f"{key}={value}" for key, value in source_counts.items())
        + f" network_pending={len(missing)}",
        flush=True,
    )
    if not missing:
        return labels

    workers = max(1, _env_int("TELONEX_CHURN_BTC_MODEL_LABEL_WORKERS", 24))
    progress_every = max(1, _env_int("TELONEX_CHURN_BTC_MODEL_LABEL_PROGRESS_EVERY", 500))
    semaphore = asyncio.Semaphore(workers)
    completed = 0

    async def load_one(market_start_ts: int) -> tuple[int, float | None]:
        async with semaphore:
            return market_start_ts, await _resolved_up(_market_slug(market_start_ts))

    tasks = [asyncio.create_task(load_one(market_start_ts)) for market_start_ts in missing]
    for task in asyncio.as_completed(tasks):
        market_start_ts, resolved = await task
        labels[market_start_ts] = resolved
        completed += 1
        if completed % progress_every == 0 or completed == len(missing):
            print(
                f"label network progress: {completed}/{len(missing)} markets "
                f"known={sum(value is not None for value in labels.values())}",
                flush=True,
            )
    return labels


def _market_slug(market_start_ts: int) -> str:
    return f"btc-updown-5m-{market_start_ts}"


async def _build_dataset(
    *,
    start_ts: int,
    windows: int,
    market_starts: tuple[int, ...] | None = None,
    snapshot_seconds: tuple[int, ...],
    max_age_seconds: int,
    depth_levels: int,
    extra_spot_symbols: tuple[str, ...] = (),
    use_spot_quotes: bool = False,
    quote_max_age_seconds: int = 3,
) -> list[dict[str, Any]]:
    starts = (
        tuple(start_ts + (index * _WINDOW_SECONDS) for index in range(windows))
        if market_starts is None
        else market_starts
    )
    if not starts:
        return []
    end_ts = max(starts) + _WINDOW_SECONDS
    max_book_age_seconds = int(max_age_seconds)
    btc = _load_btc_features(
        min(starts),
        end_ts,
        book_depth_levels=depth_levels,
        book_max_age_seconds=max_book_age_seconds,
    )
    btc_books = _load_btc_book_snapshots(
        starts=starts,
        snapshot_seconds=snapshot_seconds,
        max_age_seconds=max_book_age_seconds,
        depth_levels=depth_levels,
    )
    btc_quotes = (
        _load_spot_quote_snapshots(
            "btcusdt",
            starts=starts,
            snapshot_seconds=snapshot_seconds,
            max_age_seconds=quote_max_age_seconds,
            prefix="btc",
        )
        if use_spot_quotes
        else {}
    )
    extra_spot_stores = {
        symbol: _load_spot_features(
            symbol,
            min(starts),
            end_ts,
            book_depth_levels=depth_levels,
            book_max_age_seconds=max_book_age_seconds,
        )
        for symbol in extra_spot_symbols
    }
    extra_spot_books = {
        symbol: _load_spot_book_snapshots(
            symbol,
            starts=starts,
            snapshot_seconds=snapshot_seconds,
            max_age_seconds=max_book_age_seconds,
            depth_levels=depth_levels,
            prefix=_spot_feature_prefix(symbol),
        )
        for symbol in extra_spot_symbols
    }
    extra_spot_quotes = (
        {
            symbol: _load_spot_quote_snapshots(
                symbol,
                starts=starts,
                snapshot_seconds=snapshot_seconds,
                max_age_seconds=quote_max_age_seconds,
                prefix=_spot_feature_prefix(symbol),
            )
            for symbol in extra_spot_symbols
        }
        if use_spot_quotes
        else {}
    )
    feature_columns = _feature_columns(
        extra_spot_symbols,
        use_spot_quotes=use_spot_quotes,
    )
    rows: list[dict[str, Any]] = []
    conn = duckdb.connect(":memory:")
    labels = await _resolved_up_labels(starts, btc=btc)
    skipped: dict[str, int] = {
        "label": 0,
        "book": 0,
        "btc": 0,
        "btc_book": 0,
        "btc_quote": 0,
        "extra_spot": 0,
        "features": 0,
    }
    progress_every = max(1, _env_int("TELONEX_CHURN_BTC_MODEL_DATASET_PROGRESS_EVERY", 250))
    for index, market_start_ts in enumerate(starts):
        slug = _market_slug(market_start_ts)
        resolved_up = labels.get(market_start_ts)
        if resolved_up is None:
            skipped["label"] += 1
            continue
        yes_snapshots = _market_snapshot_features(
            conn,
            slug=slug,
            outcome="Up",
            market_start_ts=market_start_ts,
            snapshot_seconds=snapshot_seconds,
            max_age_seconds=max_age_seconds,
            depth_levels=depth_levels,
        )
        no_snapshots = _market_snapshot_features(
            conn,
            slug=slug,
            outcome="Down",
            market_start_ts=market_start_ts,
            snapshot_seconds=snapshot_seconds,
            max_age_seconds=max_age_seconds,
            depth_levels=depth_levels,
        )
        start_price = btc.price_at(market_start_ts)
        if not math.isfinite(start_price):
            skipped["btc"] += 1
            continue
        for seconds_left in snapshot_seconds:
            yes = yes_snapshots.get(seconds_left)
            no = no_snapshots.get(seconds_left)
            if yes is None or no is None:
                skipped["book"] += 1
                continue
            snapshot_ts = market_start_ts + _WINDOW_SECONDS - seconds_left
            current_price = btc.price_at(snapshot_ts)
            if not math.isfinite(current_price):
                skipped["btc"] += 1
                continue
            btc_book = btc_books.get(snapshot_ts)
            if btc_book is None:
                skipped["btc_book"] += 1
                continue
            btc_quote = btc_quotes.get(snapshot_ts) if use_spot_quotes else None
            if use_spot_quotes and btc_quote is None:
                skipped["btc_quote"] += 1
                continue
            row = {
                "slug": slug,
                "market_index": index,
                "market_start_ts": market_start_ts,
                "snapshot_ts": snapshot_ts,
                "seconds_left": seconds_left,
                "resolved_up": resolved_up,
                "btc_price": current_price,
                "btc_start_price": start_price,
                "price_diff": current_price - start_price,
                "return_since_start": (current_price / start_price) - 1.0,
                "momentum_15s": btc.momentum(snapshot_ts, 15),
                "momentum_30s": btc.momentum(snapshot_ts, 30),
                "momentum_60s": btc.momentum(snapshot_ts, 60),
                "volatility_60s": btc.volatility(snapshot_ts, 60),
                "volume_60s": btc.volume(snapshot_ts, 60),
                "btc_book_mid": btc_book["btc_book_mid"],
                "btc_book_spread": btc_book["btc_book_spread"],
                "btc_book_spread_bps": btc_book["btc_book_spread_bps"],
                "btc_book_bid_size": btc_book["btc_book_bid_size"],
                "btc_book_ask_size": btc_book["btc_book_ask_size"],
                "btc_book_bid_depth": btc_book["btc_book_bid_depth"],
                "btc_book_ask_depth": btc_book["btc_book_ask_depth"],
                "btc_book_imbalance": btc_book["btc_book_imbalance"],
                "btc_book_microprice": btc_book["btc_book_microprice"],
                "btc_book_microprice_diff": btc_book["btc_book_microprice_diff"],
                "btc_trade_book_diff": current_price - btc_book["btc_book_mid"],
                "btc_book_age_seconds": btc_book["btc_book_age_seconds"],
                "yes_bid": yes["bid"],
                "yes_ask": yes["ask"],
                "yes_mid": yes["mid"],
                "yes_spread": yes["spread"],
                "yes_bid_size": yes["bid_size"],
                "yes_ask_size": yes["ask_size"],
                "yes_bid_depth": yes["bid_depth"],
                "yes_ask_depth": yes["ask_depth"],
                "yes_book_imbalance": yes["book_imbalance"],
                "yes_microprice": yes["microprice"],
                "yes_book_age_seconds": yes["book_age_seconds"],
                "no_bid": no["bid"],
                "no_ask": no["ask"],
                "no_mid": no["mid"],
                "no_spread": no["spread"],
                "no_bid_size": no["bid_size"],
                "no_ask_size": no["ask_size"],
                "no_bid_depth": no["bid_depth"],
                "no_ask_depth": no["ask_depth"],
                "no_book_imbalance": no["book_imbalance"],
                "no_microprice": no["microprice"],
                "no_book_age_seconds": no["book_age_seconds"],
                "yes_no_ask_cost": yes["ask"] + no["ask"],
            }
            if use_spot_quotes and not _add_spot_quote_features(
                row,
                prefix="btc",
                quote=btc_quote or {},
                trade_price=current_price,
                book_mid=btc_book["btc_book_mid"],
            ):
                skipped["btc_quote"] += 1
                continue
            extra_ok = True
            for symbol, store in extra_spot_stores.items():
                quote = extra_spot_quotes.get(symbol, {}).get(snapshot_ts)
                if not _add_extra_spot_features(
                    row,
                    prefix=_spot_feature_prefix(symbol),
                    store=store,
                    books=extra_spot_books[symbol],
                    quote=quote,
                    market_start_ts=market_start_ts,
                    snapshot_ts=snapshot_ts,
                    use_spot_quotes=use_spot_quotes,
                ):
                    extra_ok = False
                    break
            if not extra_ok:
                skipped["extra_spot"] += 1
                continue
            if not all(math.isfinite(float(row[column])) for column in feature_columns):
                skipped["features"] += 1
                continue
            rows.append(row)
        if (index + 1) % progress_every == 0 or index + 1 == len(starts):
            print(
                f"dataset progress: {index + 1}/{len(starts)} markets rows={len(rows)} "
                f"skipped={skipped}",
                flush=True,
            )
    conn.close()
    return rows


def _matrix(rows: list[dict[str, Any]], columns: tuple[str, ...]) -> tuple[np.ndarray, np.ndarray]:
    x = np.array([[float(row[column]) for column in columns] for row in rows], dtype=np.float64)
    y = np.array([float(row["resolved_up"]) for row in rows], dtype=np.float64)
    return x, y


def _fit_logistic(
    rows: list[dict[str, Any]],
    *,
    columns: tuple[str, ...],
    learning_rate: float,
    steps: int,
    l2: float,
) -> LogisticModel:
    x, y = _matrix(rows, columns)
    means = x.mean(axis=0)
    scales = x.std(axis=0)
    scales[scales < 1e-9] = 1.0
    xz = (x - means) / scales
    weights = np.zeros(xz.shape[1], dtype=np.float64)
    bias = 0.0
    for _ in range(steps):
        logits = np.clip(xz @ weights + bias, -40.0, 40.0)
        probs = 1.0 / (1.0 + np.exp(-logits))
        error = probs - y
        grad_w = (xz.T @ error) / len(y) + (l2 * weights)
        grad_b = float(np.mean(error))
        weights -= learning_rate * grad_w
        bias -= learning_rate * grad_b
    return LogisticModel(
        columns=columns,
        means=tuple(float(value) for value in means),
        scales=tuple(float(value) for value in scales),
        weights=tuple(float(value) for value in weights),
        bias=float(bias),
    )


def _predict(model: LogisticModel, rows: list[dict[str, Any]]) -> np.ndarray:
    x, _ = _matrix(rows, model.columns)
    means = np.array(model.means, dtype=np.float64)
    scales = np.array(model.scales, dtype=np.float64)
    weights = np.array(model.weights, dtype=np.float64)
    logits = np.clip(((x - means) / scales) @ weights + model.bias, -40.0, 40.0)
    return 1.0 / (1.0 + np.exp(-logits))


def _auc(y: np.ndarray, p: np.ndarray) -> float | None:
    positives = int(np.sum(y == 1.0))
    negatives = int(np.sum(y == 0.0))
    if positives == 0 or negatives == 0:
        return None
    order = np.argsort(p)
    ranks = np.empty_like(order, dtype=np.float64)
    ranks[order] = np.arange(1, len(p) + 1, dtype=np.float64)
    pos_rank_sum = float(np.sum(ranks[y == 1.0]))
    return (pos_rank_sum - (positives * (positives + 1) / 2.0)) / (positives * negatives)


def _classification_metrics(
    rows: list[dict[str, Any]],
    probs: np.ndarray,
    *,
    columns: tuple[str, ...] = _FEATURE_COLUMNS,
) -> dict[str, float | None]:
    _, y = _matrix(rows, columns)
    clipped = np.clip(probs, 1e-6, 1.0 - 1e-6)
    return {
        "rows": float(len(rows)),
        "base_rate": float(np.mean(y)) if len(y) else None,
        "brier": float(np.mean((probs - y) ** 2)) if len(y) else None,
        "log_loss": float(np.mean(-(y * np.log(clipped) + (1.0 - y) * np.log(1.0 - clipped))))
        if len(y)
        else None,
        "accuracy": float(np.mean((probs >= 0.5) == (y == 1.0))) if len(y) else None,
        "auc": _auc(y, probs) if len(y) else None,
    }


def _max_drawdown(equity_values: list[float]) -> float:
    peak = -math.inf
    max_dd = 0.0
    for value in equity_values:
        peak = max(peak, value)
        max_dd = max(max_dd, peak - value)
    return max_dd


def _release_due(
    releases: list[tuple[int, float]], cash: float, now_ts: int
) -> tuple[float, list[tuple[int, float]]]:
    retained: list[tuple[int, float]] = []
    for release_ts, payout in releases:
        if release_ts <= now_ts:
            cash += payout
        else:
            retained.append((release_ts, payout))
    return cash, retained


def _selected_direction(side: str) -> float:
    return 1.0 if side == "yes" else -1.0


def _passes_momentum_alignment(row: dict[str, Any], *, side: str, mode: str) -> bool:
    direction = _selected_direction(side)
    price_diff = direction * float(row["price_diff"])
    momentum_15s = direction * float(row["momentum_15s"])
    momentum_30s = direction * float(row["momentum_30s"])
    mode = mode.strip().casefold()
    if mode in {"", "none"}:
        return True
    if mode == "m15_m30":
        return momentum_15s >= 0.0 and momentum_30s >= 0.0
    if mode == "pdiff_m15_m30":
        return price_diff > 0.0 and momentum_15s >= 0.0 and momentum_30s >= 0.0
    if mode == "reject_m15_m30_opposed":
        return not (momentum_15s < 0.0 and momentum_30s < 0.0)
    if mode == "reject_two_of_three_opposed":
        return sum(value < 0.0 for value in (price_diff, momentum_15s, momentum_30s)) <= 1
    if mode == "momentum_vote":
        votes = (
            (1 if price_diff > 0.0 else -1 if price_diff < 0.0 else 0)
            + (1 if momentum_15s > 0.0 else -1 if momentum_15s < 0.0 else 0)
            + (1 if momentum_30s > 0.0 else -1 if momentum_30s < 0.0 else 0)
        )
        return votes >= 2
    raise ValueError(f"Unsupported momentum alignment mode: {mode}")


def _passes_context_quality_gates(
    row: dict[str, Any],
    *,
    side: str,
    selected_probability: float,
) -> bool:
    direction = _selected_direction(side)
    signed_price_diff = direction * float(row["price_diff"])
    signed_momentum_30s = direction * float(row["momentum_30s"])
    signed_momentum_60s = direction * float(row["momentum_60s"])

    max_ask_cost = _env_float("TELONEX_CHURN_BTC_MODEL_MAX_YES_NO_ASK_COST", 0.0)
    if max_ask_cost > 0.0 and float(row["yes_no_ask_cost"]) > max_ask_cost:
        return False

    adverse_floor = _env_float("TELONEX_CHURN_BTC_MODEL_ADVERSE_PRICE_DIFF_FLOOR", 0.0)
    if adverse_floor > 0.0 and signed_price_diff <= -adverse_floor:
        min_momentum = _env_float("TELONEX_CHURN_BTC_MODEL_ADVERSE_MIN_SIGNED_MOMENTUM_30S", 0.0)
        if signed_momentum_30s < min_momentum:
            return False

    exhausted_floor = _env_float("TELONEX_CHURN_BTC_MODEL_EXHAUSTED_PRICE_DIFF_FLOOR", 0.0)
    exhausted_min_probability = _env_float(
        "TELONEX_CHURN_BTC_MODEL_EXHAUSTED_MIN_SELECTED_PROBABILITY",
        0.0,
    )
    if exhausted_floor > 0.0 and exhausted_min_probability > 0.0:
        if (
            signed_price_diff >= exhausted_floor
            and signed_momentum_60s < 0.0
            and selected_probability < exhausted_min_probability
        ):
            return False

    volatile_floor = _env_float("TELONEX_CHURN_BTC_MODEL_VOLATILE_PRICE_DIFF_FLOOR", 0.0)
    volatile_min_probability = _env_float(
        "TELONEX_CHURN_BTC_MODEL_VOLATILE_MIN_SELECTED_PROBABILITY",
        0.0,
    )
    if volatile_floor > 0.0 and volatile_min_probability > 0.0:
        if (
            float(row["volatility_60s"]) >= volatile_floor
            and selected_probability < volatile_min_probability
        ):
            return False
    return True


def _passes_research_quality_gates(
    row: dict[str, Any],
    *,
    side: str,
    ask_price: float,
    selected_probability: float,
) -> bool:
    ask_size = float(row["yes_ask_size"] if side == "yes" else row["no_ask_size"])
    spread = float(row["yes_spread"] if side == "yes" else row["no_spread"])
    if ask_price < _env_float("TELONEX_CHURN_BTC_MODEL_MIN_ASK_PRICE", 0.0):
        return False
    if ask_size < _env_float("TELONEX_CHURN_BTC_MODEL_MIN_VISIBLE_SIZE", 0.0):
        return False
    if spread > _env_float("TELONEX_CHURN_BTC_MODEL_MAX_SPREAD", 1.0):
        return False
    if selected_probability < _env_float("TELONEX_CHURN_BTC_MODEL_MIN_SELECTED_PROBABILITY", 0.0):
        return False
    if not _passes_momentum_alignment(
        row,
        side=side,
        mode=os.getenv("TELONEX_CHURN_BTC_MODEL_MOMENTUM_ALIGNMENT", "none"),
    ):
        return False

    expensive_floor = _env_float("TELONEX_CHURN_BTC_MODEL_EXPENSIVE_ASK_FLOOR", 1.0)
    if ask_price >= expensive_floor:
        expensive_min_probability = _env_float(
            "TELONEX_CHURN_BTC_MODEL_EXPENSIVE_MIN_SELECTED_PROBABILITY",
            0.0,
        )
        if selected_probability < expensive_min_probability:
            return False
        min_signed_momentum = _env_float(
            "TELONEX_CHURN_BTC_MODEL_EXPENSIVE_MIN_SIGNED_MOMENTUM_30S",
            0.0,
        )
        signed_momentum_30s = _selected_direction(side) * float(row["momentum_30s"])
        if signed_momentum_30s < min_signed_momentum:
            return False

    return _passes_context_quality_gates(
        row,
        side=side,
        selected_probability=selected_probability,
    )


def _evaluate_policy(
    rows: list[dict[str, Any]],
    probs: np.ndarray,
    policy: Policy,
    *,
    quantity: float,
    initial_cash: float,
    taker_fee_rate: float,
    settlement_delay_seconds: int,
) -> dict[str, Any]:
    max_ask_price = _env_float("TELONEX_CHURN_BTC_MODEL_MAX_ASK_PRICE", 1.0)
    min_realized_ev = _env_float("TELONEX_CHURN_BTC_MODEL_MIN_REALIZED_EV", -1_000_000.0)
    max_worst_trade_loss = _env_float("TELONEX_CHURN_BTC_MODEL_MAX_WORST_TRADE_LOSS", 0.0)
    cash = initial_cash
    releases: list[tuple[int, float]] = []
    equity_values = [initial_cash]
    traded_slugs: set[str] = set()
    trades: list[dict[str, Any]] = []
    skipped_cash = 0
    allowed_seconds = set(policy.seconds_left)
    sorted_items = sorted(zip(rows, probs, strict=True), key=lambda item: item[0]["snapshot_ts"])
    for row, prob in sorted_items:
        cash, releases = _release_due(releases, cash, int(row["snapshot_ts"]))
        slug = str(row["slug"])
        if slug in traded_slugs or int(row["seconds_left"]) not in allowed_seconds:
            continue
        yes_edge = float(prob) - float(row["yes_ask"])
        no_edge = (1.0 - float(prob)) - float(row["no_ask"])
        if max(yes_edge, no_edge) < policy.edge:
            continue
        side = "yes" if yes_edge >= no_edge else "no"
        ask_price = float(row["yes_ask"] if side == "yes" else row["no_ask"])
        if ask_price > max_ask_price:
            continue
        edge = yes_edge if side == "yes" else no_edge
        selected_probability = float(prob) if side == "yes" else 1.0 - float(prob)
        if not _passes_research_quality_gates(
            row,
            side=side,
            ask_price=ask_price,
            selected_probability=selected_probability,
        ):
            continue
        resolved_up = float(row["resolved_up"])
        win = resolved_up == 1.0 if side == "yes" else resolved_up == 0.0
        fee = quantity * taker_fee_rate * ask_price * (1.0 - ask_price)
        cost = (quantity * ask_price) + fee
        if cash + 1e-9 < cost:
            skipped_cash += 1
            continue
        cash -= cost
        payout = quantity if win else 0.0
        pnl = payout - cost
        release_ts = int(row["market_start_ts"]) + _WINDOW_SECONDS + settlement_delay_seconds
        releases.append((release_ts, payout))
        traded_slugs.add(slug)
        trades.append(
            {
                "slug": slug,
                "snapshot_ts": int(row["snapshot_ts"]),
                "seconds_left": int(row["seconds_left"]),
                "side": side,
                "prob_up": float(prob),
                "selected_probability": selected_probability,
                "ask_price": ask_price,
                "edge": edge,
                "quantity": quantity,
                "cost": cost,
                "payout": payout,
                "pnl": pnl,
                "resolved_up": resolved_up,
            }
        )
        equity_values.append(cash + sum(payout for _, payout in releases))
    for release_ts, _ in sorted(releases):
        cash, releases = _release_due(releases, cash, release_ts)
        equity_values.append(cash + sum(payout for _, payout in releases))
    pnl = cash - initial_cash
    wins = sum(1 for trade in trades if trade["payout"] > 0.0)
    losses = len(trades) - wins
    winning_pnl = sum(trade["pnl"] for trade in trades if trade["pnl"] > 0.0)
    losing_pnl = sum(trade["pnl"] for trade in trades if trade["pnl"] < 0.0)
    avg_ask_price = (
        sum(float(trade["ask_price"]) for trade in trades) / len(trades) if trades else 0.0
    )
    avg_win_payout = (
        sum(float(trade["payout"]) for trade in trades if trade["payout"] > 0.0) / wins
        if wins
        else 0.0
    )
    avg_loss_cost = (
        sum(float(trade["cost"]) for trade in trades if trade["payout"] <= 0.0) / losses
        if losses
        else 0.0
    )
    realized_ev_per_trade = pnl / len(trades) if trades else 0.0
    profit_factor = winning_pnl / abs(losing_pnl) if losing_pnl < 0.0 else math.inf
    worst_trade_pnl = min((float(trade["pnl"]) for trade in trades), default=0.0)
    max_drawdown = _max_drawdown(equity_values)
    score = pnl - (0.5 * max_drawdown)
    if len(trades) < _env_int("TELONEX_CHURN_BTC_MODEL_MIN_TRADES", 3):
        score -= 10.0
    if trades and realized_ev_per_trade < min_realized_ev:
        score -= 100.0 * (min_realized_ev - realized_ev_per_trade)
    if max_worst_trade_loss > 0.0 and worst_trade_pnl < -max_worst_trade_loss:
        score -= 100.0 * ((-max_worst_trade_loss) - worst_trade_pnl)
    return {
        "policy": policy.name,
        "edge": policy.edge,
        "seconds_left": ",".join(str(value) for value in policy.seconds_left),
        "score": score,
        "pnl": pnl,
        "roi": pnl / initial_cash if initial_cash > 0.0 else 0.0,
        "max_drawdown_currency": max_drawdown,
        "trades": len(trades),
        "wins": wins,
        "losing_trade_count": losses,
        "win_rate": wins / len(trades) if trades else 0.0,
        "avg_ask_price": avg_ask_price,
        "avg_win_payout": avg_win_payout,
        "avg_loss_cost": avg_loss_cost,
        "realized_ev_per_trade": realized_ev_per_trade,
        "profit_factor": profit_factor,
        "worst_trade_pnl": worst_trade_pnl,
        "skipped_cash": skipped_cash,
        "ending_cash": cash,
        "trades_detail": trades,
    }


def _policy_grid(snapshot_seconds: tuple[int, ...]) -> list[Policy]:
    configured_edges = os.getenv("TELONEX_CHURN_BTC_MODEL_EDGES")
    if configured_edges:
        edges = tuple(
            float(value.strip()) for value in configured_edges.split(",") if value.strip()
        )
    else:
        edges = (0.02, 0.04, 0.06, 0.08, 0.10, 0.12, 0.15)
    bucket_sets = [
        snapshot_seconds,
        tuple(value for value in snapshot_seconds if value <= 120),
        tuple(value for value in snapshot_seconds if value <= 60),
        tuple(value for value in snapshot_seconds if value <= 30),
    ]
    bucket_sets.extend((value,) for value in snapshot_seconds)
    unique_bucket_sets: list[tuple[int, ...]] = []
    seen: set[tuple[int, ...]] = set()
    for buckets in bucket_sets:
        if not buckets or buckets in seen:
            continue
        seen.add(buckets)
        unique_bucket_sets.append(buckets)
    return [
        Policy(edge=edge, seconds_left=buckets) for edge in edges for buckets in unique_bucket_sets
    ]


def _split_rows(
    rows: list[dict[str, Any]],
    *,
    train_windows: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    train_rows = [row for row in rows if int(row["market_index"]) < train_windows]
    holdout_rows = [row for row in rows if int(row["market_index"]) >= train_windows]
    return train_rows, holdout_rows


def _split_rows_three(
    rows: list[dict[str, Any]],
    *,
    train_windows: int,
    validation_windows: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    validation_end = train_windows + validation_windows
    train_rows = [row for row in rows if int(row["market_index"]) < train_windows]
    validation_rows = [
        row for row in rows if train_windows <= int(row["market_index"]) < validation_end
    ]
    test_rows = [row for row in rows if int(row["market_index"]) >= validation_end]
    return train_rows, validation_rows, test_rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("")
        return
    slim_rows = [
        {key: value for key, value in row.items() if key != "trades_detail"} for row in rows
    ]
    fieldnames = sorted({key for row in slim_rows for key in row})
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(slim_rows)


def _available_cached_btc_market_starts() -> list[int]:
    root = Path.home() / ".cache/nautilus_trader/telonex/api-days"
    starts: set[int] = set()
    for path in root.glob("*/polymarket/book_snapshot_full/btc-updown-5m-*"):
        try:
            starts.add(int(path.name.rsplit("-", 1)[1]))
        except ValueError:
            continue
    return sorted(starts)


def _write_cached_market_manifest() -> Path:
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    starts = _available_cached_btc_market_starts()
    rows = [
        {
            "market_start_ts": value,
            "market_start": datetime.fromtimestamp(value, UTC).isoformat().replace("+00:00", "Z"),
            "slug": _market_slug(value),
        }
        for value in starts
    ]
    path = ARTIFACT_ROOT / "telonex_btc_5m_cached_markets.csv"
    _write_csv(path, rows)
    if starts:
        print(
            f"cached BTC 5m markets: count={len(starts)} "
            f"first={rows[0]['market_start']} last={rows[-1]['market_start']}"
        )
    else:
        print("cached BTC 5m markets: count=0")
    print(f"Cached market manifest CSV: {path}")
    return path


def _json_default(value: object) -> object:
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(f"Object of type {type(value)!r} is not JSON serializable")


def _resolved_up_cache() -> dict[str, float | None]:
    global _RESOLVED_UP_CACHE
    if _RESOLVED_UP_CACHE is not None:
        return _RESOLVED_UP_CACHE
    if not _RESOLVED_UP_CACHE_PATH.exists():
        _RESOLVED_UP_CACHE = {}
        return _RESOLVED_UP_CACHE
    raw = json.loads(_RESOLVED_UP_CACHE_PATH.read_text())
    if not isinstance(raw, dict):
        raise RuntimeError(f"Invalid resolved-up cache: {_RESOLVED_UP_CACHE_PATH}")
    cache: dict[str, float | None] = {}
    for key, value in raw.items():
        cache[str(key)] = None if value is None else float(value)
    _RESOLVED_UP_CACHE = cache
    return cache


def _resolved_up_from_payload(payload: dict[str, Any]) -> float | None:
    outcomes_raw = payload.get("outcomes")
    prices_raw = payload.get("outcomePrices")
    try:
        outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw
        prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
    except (TypeError, ValueError):
        return None
    if not isinstance(outcomes, list) or not isinstance(prices, list):
        return None
    if len(outcomes) != len(prices):
        return None
    by_outcome: dict[str, float] = {}
    for outcome, price in zip(outcomes, prices, strict=True):
        try:
            by_outcome[str(outcome).strip().lower()] = float(price)
        except (TypeError, ValueError):
            return None
    up = by_outcome.get("up")
    down = by_outcome.get("down")
    if up is None or down is None:
        return None
    if up >= 0.999 and down <= 0.001:
        return 1.0
    if down >= 0.999 and up <= 0.001:
        return 0.0
    return None


def _local_gamma_resolved_up_cache() -> dict[str, float]:
    global _LOCAL_GAMMA_RESOLVED_UP_CACHE
    if _LOCAL_GAMMA_RESOLVED_UP_CACHE is not None:
        return _LOCAL_GAMMA_RESOLVED_UP_CACHE

    root = Path.home() / ".cache/nautilus_trader/polymarket_metadata/v1/gamma-market"
    values: dict[str, float] = {}
    if root.exists():
        for path in root.glob("*.json"):
            try:
                payload = json.loads(path.read_text()).get("payload", {})
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            slug = payload.get("slug")
            if not isinstance(slug, str) or not slug.startswith("btc-updown-5m-"):
                continue
            resolved = _resolved_up_from_payload(payload)
            if resolved is not None:
                values[slug] = resolved
    _LOCAL_GAMMA_RESOLVED_UP_CACHE = values
    return values


def _flush_resolved_up_cache(*, force: bool = False) -> None:
    global _RESOLVED_UP_DIRTY
    if _RESOLVED_UP_CACHE is None or (_RESOLVED_UP_DIRTY <= 0 and not force):
        return
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    tmp = _RESOLVED_UP_CACHE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(_RESOLVED_UP_CACHE, sort_keys=True))
    tmp.replace(_RESOLVED_UP_CACHE_PATH)
    _RESOLVED_UP_DIRTY = 0


async def _run_async() -> None:
    load_dotenv()
    if os.getenv("TELONEX_CHURN_BTC_MODEL_LIST_CACHED_MARKETS") == "1":
        _write_cached_market_manifest()
        return

    use_cached_markets = os.getenv("TELONEX_CHURN_BTC_MODEL_USE_CACHED_MARKETS") == "1"
    cached_market_starts: tuple[int, ...] | None = None
    if use_cached_markets:
        starts = _available_cached_btc_market_starts()
        start_index = _env_int("TELONEX_CHURN_BTC_MODEL_CACHE_START_INDEX", 0)
        max_markets = _env_int("TELONEX_CHURN_BTC_MODEL_CACHE_MAX_MARKETS", 0)
        if start_index < 0:
            raise ValueError("TELONEX_CHURN_BTC_MODEL_CACHE_START_INDEX must be >= 0")
        starts = starts[start_index:]
        if max_markets > 0:
            starts = starts[:max_markets]
        if not starts:
            raise RuntimeError("No cached BTC 5m markets available for model run.")
        cached_market_starts = tuple(starts)
        start_ts = cached_market_starts[0]
        windows = len(cached_market_starts)
    else:
        start_ts = _env_int("TELONEX_CHURN_BTC_MODEL_START", _DEFAULT_START_TS)
        windows = _env_int("TELONEX_CHURN_BTC_MODEL_WINDOWS", _DEFAULT_WINDOWS)
    snapshot_seconds = tuple(
        int(value.strip())
        for value in os.getenv(
            "TELONEX_CHURN_BTC_MODEL_SNAPSHOT_SECONDS",
            ",".join(str(value) for value in _DEFAULT_SNAPSHOT_SECONDS),
        ).split(",")
        if value.strip()
    )
    if windows < 12:
        raise ValueError("TELONEX_CHURN_BTC_MODEL_WINDOWS must be >= 12")
    if not snapshot_seconds:
        raise ValueError("TELONEX_CHURN_BTC_MODEL_SNAPSHOT_SECONDS must not be empty")
    extra_spot_symbols = _extra_spot_symbols()
    use_spot_quotes = _env_bool("TELONEX_CHURN_BTC_MODEL_USE_SPOT_QUOTES")
    feature_columns = _feature_columns(
        extra_spot_symbols,
        use_spot_quotes=use_spot_quotes,
    )

    label = _run_label()
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    if extra_spot_symbols:
        extra_spot_text = ", ".join(symbol.upper() for symbol in extra_spot_symbols)
        quote_text = " plus spot quote BBO context" if use_spot_quotes else ""
        print(
            "Strategy hypothesis: BTC 5m UP probability should improve when Telonex "
            "Binance BTC momentum/volatility, optional cross-asset spot context "
            f"({extra_spot_text}){quote_text}, and Telonex Polymarket YES/NO book imbalance "
            "are evaluated on forward holdout data."
        )
    else:
        quote_text = " and spot quote BBO context" if use_spot_quotes else ""
        print(
            "Strategy hypothesis: BTC 5m UP probability should improve when Telonex "
            f"Binance BTC momentum/volatility{quote_text} is combined with Telonex Polymarket "
            "YES/NO book imbalance and microprice. Trade only when the model clears "
            "the visible ask by a fixed edge, evaluated on a forward holdout."
        )
    try:
        rows = await _build_dataset(
            start_ts=start_ts,
            windows=windows,
            market_starts=cached_market_starts,
            snapshot_seconds=snapshot_seconds,
            max_age_seconds=_env_int("TELONEX_CHURN_BTC_MODEL_MAX_BOOK_AGE_SECONDS", 8),
            depth_levels=_env_int("TELONEX_CHURN_BTC_MODEL_DEPTH_LEVELS", 5),
            extra_spot_symbols=extra_spot_symbols,
            use_spot_quotes=use_spot_quotes,
            quote_max_age_seconds=_env_int("TELONEX_CHURN_BTC_MODEL_MAX_QUOTE_AGE_SECONDS", 3),
        )
    finally:
        _flush_resolved_up_cache(force=True)
    train_windows = _env_int("TELONEX_CHURN_BTC_MODEL_TRAIN_WINDOWS", int(windows * 2 / 3))
    validation_windows = _env_int("TELONEX_CHURN_BTC_MODEL_VALIDATION_WINDOWS", 0)
    if validation_windows > 0:
        train_rows, validation_rows, holdout_rows = _split_rows_three(
            rows,
            train_windows=train_windows,
            validation_windows=validation_windows,
        )
    else:
        train_rows, holdout_rows = _split_rows(rows, train_windows=train_windows)
        validation_rows = []
    if len(train_rows) < 50 or len(holdout_rows) < 20:
        raise RuntimeError(
            f"Not enough model rows after split: train={len(train_rows)} "
            f"holdout={len(holdout_rows)}."
        )
    if validation_windows > 0 and len(validation_rows) < 20:
        raise RuntimeError(
            f"Not enough validation rows after split: validation={len(validation_rows)}."
        )

    model = _fit_logistic(
        train_rows,
        columns=feature_columns,
        learning_rate=_env_float("TELONEX_CHURN_BTC_MODEL_LEARNING_RATE", 0.05),
        steps=_env_int("TELONEX_CHURN_BTC_MODEL_STEPS", 1200),
        l2=_env_float("TELONEX_CHURN_BTC_MODEL_L2", 0.002),
    )
    train_probs = _predict(model, train_rows)
    validation_probs = _predict(model, validation_rows) if validation_rows else np.array([])
    holdout_probs = _predict(model, holdout_rows)
    train_metrics = _classification_metrics(train_rows, train_probs, columns=feature_columns)
    validation_metrics = (
        _classification_metrics(validation_rows, validation_probs, columns=feature_columns)
        if validation_rows
        else None
    )
    holdout_metrics = _classification_metrics(holdout_rows, holdout_probs, columns=feature_columns)
    grid = _policy_grid(snapshot_seconds)
    policy_kwargs = {
        "quantity": _env_float("TELONEX_CHURN_BTC_MODEL_QUANTITY", 5.0),
        "initial_cash": _env_float("TELONEX_CHURN_BTC_INITIAL_CASH", 20.0),
        "taker_fee_rate": _env_float("TELONEX_CHURN_BTC_MODEL_TAKER_FEE_RATE", 0.0),
        "settlement_delay_seconds": _env_int(
            "TELONEX_CHURN_BTC_MODEL_SETTLEMENT_DELAY_SECONDS",
            60,
        ),
    }
    train_policy_rows = [
        _evaluate_policy(train_rows, train_probs, policy, **policy_kwargs) for policy in grid
    ]
    train_policy_rows.sort(key=lambda row: float(row["score"]), reverse=True)
    if validation_rows:
        validation_policy_rows = [
            _evaluate_policy(validation_rows, validation_probs, policy, **policy_kwargs)
            for policy in grid
        ]
        validation_policy_rows.sort(key=lambda row: float(row["score"]), reverse=True)
        selected_policy_name = str(validation_policy_rows[0]["policy"])
    else:
        validation_policy_rows = []
        selected_policy_name = str(train_policy_rows[0]["policy"])
    selected_policy = next(policy for policy in grid if policy.name == selected_policy_name)
    holdout_policy_rows = [
        _evaluate_policy(holdout_rows, holdout_probs, policy, **policy_kwargs) for policy in grid
    ]
    holdout_policy_rows.sort(key=lambda row: float(row["score"]), reverse=True)
    selected_holdout = _evaluate_policy(
        holdout_rows,
        holdout_probs,
        selected_policy,
        **policy_kwargs,
    )

    dataset_path = ARTIFACT_ROOT / f"telonex_btc_5m_snapshot_model_{label}_dataset.csv"
    train_policy_path = ARTIFACT_ROOT / f"telonex_btc_5m_snapshot_model_{label}_train_policies.csv"
    validation_policy_path = (
        ARTIFACT_ROOT / f"telonex_btc_5m_snapshot_model_{label}_validation_policies.csv"
    )
    holdout_policy_path = (
        ARTIFACT_ROOT / f"telonex_btc_5m_snapshot_model_{label}_holdout_policies.csv"
    )
    summary_path = ARTIFACT_ROOT / f"telonex_btc_5m_snapshot_model_{label}_summary.json"
    _write_csv(dataset_path, rows)
    _write_csv(train_policy_path, train_policy_rows)
    if validation_policy_rows:
        _write_csv(validation_policy_path, validation_policy_rows)
    _write_csv(holdout_policy_path, holdout_policy_rows)
    summary = {
        "name": f"telonex_btc_5m_snapshot_model_{label}",
        "hypothesis": (
            "BTC 5m UP probability should improve when Telonex Binance BTC "
            "momentum/volatility and optional spot quote/cross-asset context "
            "are combined with Telonex Polymarket YES/NO "
            "book imbalance and microprice. The selected trading policy is "
            "chosen on the training window and then replayed unchanged on "
            "the forward holdout with $20 cash."
        ),
        "start_ts": start_ts,
        "windows": windows,
        "use_cached_markets": use_cached_markets,
        "cached_market_start_count": len(cached_market_starts or ()),
        "snapshot_seconds": snapshot_seconds,
        "extra_spot_symbols": extra_spot_symbols,
        "use_spot_quotes": use_spot_quotes,
        "label_allow_network": _env_bool("TELONEX_CHURN_BTC_MODEL_LABEL_ALLOW_NETWORK", True),
        "label_fallback_spot": _env_bool("TELONEX_CHURN_BTC_MODEL_LABEL_FALLBACK_SPOT"),
        "train_windows": train_windows,
        "validation_windows": validation_windows,
        "rows": len(rows),
        "train_rows": len(train_rows),
        "validation_rows": len(validation_rows),
        "holdout_rows": len(holdout_rows),
        "features": feature_columns,
        "model": {
            "columns": model.columns,
            "means": model.means,
            "scales": model.scales,
            "weights": model.weights,
            "bias": model.bias,
        },
        "train_metrics": train_metrics,
        "validation_metrics": validation_metrics,
        "holdout_metrics": holdout_metrics,
        "policy_assumptions": policy_kwargs,
        "best_train_policy": train_policy_rows[0],
        "best_validation_policy": validation_policy_rows[0] if validation_policy_rows else None,
        "best_holdout_policy": holdout_policy_rows[0],
        "selected_train_policy_holdout": selected_holdout,
        "selected_policy_source": "validation" if validation_policy_rows else "train",
        "dataset_csv": str(dataset_path),
        "train_policies_csv": str(train_policy_path),
        "validation_policies_csv": str(validation_policy_path) if validation_policy_rows else None,
        "holdout_policies_csv": str(holdout_policy_path),
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True, default=_json_default))
    print(
        f"model rows: train={len(train_rows)} holdout={len(holdout_rows)} "
        f"holdout_auc={holdout_metrics['auc']} holdout_brier={holdout_metrics['brier']}"
    )
    print(
        "selected policy holdout: "
        f"score={selected_holdout['score']:.4f} pnl={selected_holdout['pnl']:.4f} "
        f"trades={selected_holdout['trades']} win_rate={selected_holdout['win_rate']:.2%} "
        f"max_dd={selected_holdout['max_drawdown_currency']:.4f}"
    )
    print(f"Strategy model summary JSON: {summary_path}")
    print(f"Strategy model dataset CSV: {dataset_path}")


def run() -> None:
    asyncio.run(_run_async())


if __name__ == "__main__":
    run()
