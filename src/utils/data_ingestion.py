import asyncio
import json
import logging
import os
import time
from datetime import datetime
from typing import Any, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("DataIngestion")


YFINANCE_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "user_data", "data", "yfinance_cache"
)


def _compute_technicals(df: pd.DataFrame) -> pd.DataFrame:
    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    volume = df["volume"].values
    n = len(close)

    rsi = np.full(n, 50.0, dtype=np.float64)
    macd = np.full(n, 0.0, dtype=np.float64)
    macd_signal = np.full(n, 0.0, dtype=np.float64)
    bb_upper = np.full(n, 0.0, dtype=np.float64)
    bb_lower = np.full(n, 0.0, dtype=np.float64)

    if n > 14:
        deltas = np.diff(close, prepend=close[0])
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)
        avg_gain = np.full(n, np.nan, dtype=np.float64)
        avg_loss = np.full(n, np.nan, dtype=np.float64)
        avg_gain[14] = np.mean(gains[1:15])
        avg_loss[14] = np.mean(losses[1:15])
        for i in range(15, n):
            avg_gain[i] = (avg_gain[i - 1] * 13 + gains[i]) / 14
            avg_loss[i] = (avg_loss[i - 1] * 13 + losses[i]) / 14
        rs = avg_gain / np.maximum(avg_loss, 1e-10)
        rsi = 100 - (100 / (1 + rs))
        rsi = np.where(np.isnan(rsi), 50.0, rsi)

    if n > 26:
        ema12 = _ema(close, 12)
        ema26 = _ema(close, 26)
        macd = ema12 - ema26
        macd_signal = _ema(macd, 9)

    if n > 20:
        sma20 = np.full(n, np.nan, dtype=np.float64)
        for i in range(19, n):
            sma20[i] = np.mean(close[i - 19:i + 1])
        std20 = np.full(n, np.nan, dtype=np.float64)
        for i in range(19, n):
            std20[i] = np.std(close[i - 19:i + 1])
        bb_upper = sma20 + 2 * std20
        bb_lower = sma20 - 2 * std20
        bb_upper = np.where(np.isnan(bb_upper), close, bb_upper)
        bb_lower = np.where(np.isnan(bb_lower), close, bb_lower)

    log_returns = np.full(n, 0.0, dtype=np.float64)
    log_returns[1:] = np.diff(np.log(np.maximum(close, 1e-10)))

    log_return_1 = log_returns
    log_return_3 = np.full(n, 0.0, dtype=np.float64)
    log_return_5 = np.full(n, 0.0, dtype=np.float64)
    for i in range(2, n):
        log_return_3[i] = np.log(np.maximum(close[i] / np.maximum(close[max(0, i - 2)], 1e-10), 1e-10))
    for i in range(4, n):
        log_return_5[i] = np.log(np.maximum(close[i] / np.maximum(close[max(0, i - 4)], 1e-10), 1e-10))

    spread_bps = np.full(n, 0.0, dtype=np.float64)
    if "spread" in df.columns:
        spread_bps = df["spread"].values.astype(np.float64)
    elif "high" in df.columns and "low" in df.columns:
        spread_bps = ((high - low) / np.maximum(close, 1e-10)) * 10000

    order_imbalance = np.full(n, 0.5, dtype=np.float64)
    if volume.max() > 0:
        vol_ma = pd.Series(volume).rolling(20).mean().values
        valid_mask = np.isfinite(vol_ma) & (vol_ma > 1e-10)
        np.divide(volume, vol_ma, out=order_imbalance, where=valid_mask)
        order_imbalance = np.clip(order_imbalance, 0.0, 1.0)

    result = df.copy()
    result["rsi_14"] = rsi
    result["macd"] = macd
    result["macd_signal"] = macd_signal
    result["bb_upper"] = bb_upper
    result["bb_lower"] = bb_lower
    result["log_return_1"] = log_return_1
    result["log_return_3"] = log_return_3
    result["log_return_5"] = log_return_5
    result["spread_bps"] = spread_bps
    result["order_imbalance"] = order_imbalance

    result = result.replace([np.inf, -np.inf], np.nan)
    numeric_cols = result.select_dtypes(include=[np.number]).columns
    result[numeric_cols] = result[numeric_cols].fillna(0.0)

    return result


def _ema(values: np.ndarray, period: int) -> np.ndarray:
    alpha = 2 / (period + 1)
    out = np.full_like(values, np.nan, dtype=np.float64)
    if len(values) == 0:
        return out
    out[0] = values[0]
    for i in range(1, len(values)):
        if np.isnan(out[i - 1]):
            out[i] = values[i]
        else:
            out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
    return out


def _resolve_interval(interval: str) -> str:
    mapping = {
        "1m": "1m",
        "5m": "5m",
        "15m": "15m",
        "30m": "30m",
        "1h": "1h",
        "4h": "4h",
        "1d": "1d",
    }
    return mapping.get(interval, "5m")


class YFinanceIngestion:
    def __init__(
        self,
        store: Any,
        cache_dir: str = YFINANCE_CACHE_DIR,
    ) -> None:
        self.store = store
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)

    def fetch_and_store(
        self,
        ticker: str,
        interval: str = "5m",
        period: str = "7d",
    ) -> int:
        try:
            import yfinance as yf
        except ImportError:
            logger.error("yfinance not installed. pip install yfinance")
            return 0

        interval = _resolve_interval(interval)
        logger.info(f"Downloading {ticker} ({interval}/{period}) from yfinance...")
        try:
            tk = yf.Ticker(ticker)
            df = tk.history(period=period, interval=interval)
        except Exception as e:
            logger.error(f"yfinance download failed for {ticker}: {e}")
            return 0

        if df.empty:
            logger.warning(f"No data returned for {ticker}")
            return 0

        df = df.rename(columns={
            "Open": "open", "High": "high", "Low": "low",
            "Close": "close", "Volume": "volume",
        })
        df = df[["open", "high", "low", "close", "volume"]].copy()
        df = _compute_technicals(df)

        base_ts = time.time()
        rows = []
        feature_names = [c for c in df.columns if c not in ("open", "high", "low", "close", "volume")]
        feature_names = list(dict.fromkeys(feature_names))

        for i, (idx, row) in enumerate(df.iterrows()):
            ts = base_ts + i * 300
            if isinstance(idx, pd.Timestamp):
                ts = idx.timestamp()
            rows.append((ts, ticker, "open", float(row["open"])))
            rows.append((ts, ticker, "high", float(row["high"])))
            rows.append((ts, ticker, "low", float(row["low"])))
            rows.append((ts, ticker, "close", float(row["close"])))
            rows.append((ts, ticker, "volume", float(row["volume"])))
            for fname in feature_names:
                val = row.get(fname, 0.0)
                if pd.isna(val):
                    val = 0.0
                rows.append((ts, ticker, fname, float(val)))

        self.store._conn.executemany("""
            INSERT INTO features_computed (timestamp, ticker, feature_name, feature_value)
            VALUES (?, ?, ?, ?)
        """, rows)
        self.store._conn.commit()

        n_entries = len(rows)
        logger.info(f"Stored {n_entries} features for {ticker} from yfinance")
        return n_entries

    def fetch_batch(
        self,
        tickers: list[str],
        interval: str = "5m",
        period: str = "7d",
    ) -> dict[str, int]:
        results: dict[str, int] = {}
        for ticker in tickers:
            count = self.fetch_and_store(ticker, interval, period)
            results[ticker] = count
        return results


class BinanceWSListener:
    def __init__(
        self,
        store: Any,
        tickers: Optional[list[str]] = None,
    ) -> None:
        self.store = store
        self.tickers = tickers or ["BTCUSDT", "ETHUSDT"]
        self._ws: Any = None
        self._running = False
        self.depth_stream_interval = str(os.getenv("BINANCE_DEPTH_STREAM_INTERVAL", "1000ms")).strip() or "1000ms"
        self.record_raw_depth_events = str(os.getenv("BINANCE_RECORD_RAW_DEPTH_EVENTS", "false")).strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _kline_to_ohlcv(msg: dict) -> Optional[dict]:
        k = msg.get("k", {})
        if not k:
            return None
        return {
            "timestamp": float(k["t"]) / 1000.0,
            "open": float(k["o"]),
            "high": float(k["h"]),
            "low": float(k["l"]),
            "close": float(k["c"]),
            "volume": float(k["v"]),
            "is_final": bool(k.get("x", False)),
        }

    @staticmethod
    def _depth_to_snapshot(msg: dict) -> Optional[dict]:
        # Handle both diff depth (b, a) and partial depth (bids, asks)
        bids = msg.get("b", msg.get("bids", []))
        asks = msg.get("a", msg.get("asks", []))
        if not bids or not asks:
            return None
        try:
            best_bid = float(bids[0][0])
            best_ask = float(asks[0][0])
            bid_vol = sum(float(b[1]) for b in bids[:10])
            ask_vol = sum(float(a[1]) for a in asks[:10])
            mid = (best_bid + best_ask) / 2 if best_bid > 0 and best_ask > 0 else 0.0
            spread_bps = ((best_ask - best_bid) / mid) * 10000 if mid > 0 else 0.0
            imbalance = bid_vol / (bid_vol + ask_vol) if (bid_vol + ask_vol) > 0 else 0.5
            
            # Use event time 'E' or transaction time 'T' or current time
            ts = float(msg.get("E", msg.get("T", time.time() * 1000))) / 1000.0
            
            return {
                "timestamp": ts,
                "mid_price": mid,
                "spread_bps": spread_bps,
                "order_imbalance": imbalance,
                "bid_volume": bid_vol,
                "ask_volume": ask_vol,
            }
        except (IndexError, ValueError, TypeError):
            return None

    def _record_kline(self, ticker: str, data: dict) -> None:
        ts = data["timestamp"]
        self.store.record_feature(ticker, "open", data["open"], ts)
        self.store.record_feature(ticker, "high", data["high"], ts)
        self.store.record_feature(ticker, "low", data["low"], ts)
        self.store.record_feature(ticker, "close", data["close"], ts)
        self.store.record_feature(ticker, "volume", data["volume"], ts)
        self.store.record_feature(ticker, "log_return_1", 0.0, ts)

        self.store.record_web_event(
            source="binance_ws",
            event_type="kline",
            payload={**data, "ticker": ticker},
            market_slug=ticker,
            condition_id="",
            timestamp=ts,
        )

    def _record_depth(self, ticker: str, data: dict) -> None:
        ts = data["timestamp"]
        self.store.record_microstructure(
            ticker=ticker,
            bid_volume=data["bid_volume"],
            ask_volume=data["ask_volume"],
            spread=data["spread_bps"],
            mid_price=data["mid_price"],
            order_imbalance=data["order_imbalance"],
        )
        
        # Throttled logging to prevent flooding
        if not hasattr(self, "_depth_counts"):
            self._depth_counts = {}
        self._depth_counts[ticker] = self._depth_counts.get(ticker, 0) + 1
        if self._depth_counts[ticker] % 100 == 0:
            logger.info(f"📊 [BINANCE] Recorded 100 depth ticks for {ticker} (Last price: {data['mid_price']:.2f})")

        if self.record_raw_depth_events:
            self.store.record_web_event(
                source="binance_ws",
                event_type="depth",
                payload={**data, "ticker": ticker},
                market_slug=ticker,
                condition_id="",
                timestamp=ts,
            )

    def start(self) -> None:
        import asyncio
        try:
            asyncio.run(self._run())
        except RuntimeError:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(self._run())

    async def _run(self) -> None:
        import websockets
        streams = "/".join(
            f"{t.lower()}@kline_1m/{t.lower()}@depth10@{self.depth_stream_interval}"
            for t in self.tickers
        )
        # Combined stream URL format
        url = f"wss://stream.binance.com:9443/stream?streams={streams}"
        logger.info(f"Connecting to Binance WS (Combined): {url[:80]}...")
        self._running = True
        
        while self._running:
            try:
                async with websockets.connect(url, ping_interval=30) as ws:
                    self._ws = ws
                    async for raw in ws:
                        if not self._running:
                            break
                        try:
                            msg = json.loads(raw)
                        except json.JSONDecodeError:
                            continue

                        # Determine stream type
                        # Combined streams wrap data: {"stream":"...", "data":{...}}
                        if "stream" in msg and "data" in msg:
                            stream_name = msg["stream"]
                            data = msg["data"]
                            ticker = stream_name.split("@")[0].upper()
                            if "kline" in stream_name:
                                ohlcv = self._kline_to_ohlcv(data)
                                if ohlcv: self._record_kline(ticker, ohlcv)
                            else:
                                depth = self._depth_to_snapshot(data)
                                if depth: self._record_depth(ticker, depth)
                        else:
                            # Direct stream format
                            event_type = msg.get("e", "")
                            ticker = msg.get("s", "")
                            if event_type == "kline":
                                ohlcv = self._kline_to_ohlcv(msg)
                                if ohlcv: self._record_kline(ticker, ohlcv)
                            elif event_type == "depthUpdate":
                                depth = self._depth_to_snapshot(msg)
                                if depth: self._record_depth(ticker, depth)
            except (websockets.ConnectionClosed, Exception) as e:
                if self._running:
                    logger.warning(f"Binance WS disconnected ({e}), reconnecting in 5s...")
                    await asyncio.sleep(5)
                else:
                    break

    def stop(self) -> None:
        self._running = False

    def fetch_historical_klines(
        self,
        ticker: str,
        interval: str = "5m",
        limit: int = 1000,
    ) -> int:
        import httpx
        interval_map = {
            "1m": "1m", "5m": "5m", "15m": "15m",
            "30m": "30m", "1h": "1h", "4h": "4h", "1d": "1d",
        }
        mapped = interval_map.get(interval, "5m")
        url = f"https://api.binance.com/api/v3/klines"
        params = {"symbol": ticker, "interval": mapped, "limit": min(limit, 1000)}
        try:
            resp = httpx.get(url, params=params, timeout=30.0)
            resp.raise_for_status()
            klines = resp.json()
        except Exception as e:
            logger.error(f"Binance historical fetch failed for {ticker}: {e}")
            return 0

        base_ts = time.time()
        rows = []
        for i, k in enumerate(klines):
            ts = float(k[0]) / 1000.0
            o, h, l, c, v = float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])
            rows.append((ts, ticker, "open", o))
            rows.append((ts, ticker, "high", h))
            rows.append((ts, ticker, "low", l))
            rows.append((ts, ticker, "close", c))
            rows.append((ts, ticker, "volume", v))

        self.store._conn.executemany("""
            INSERT INTO features_computed (timestamp, ticker, feature_name, feature_value)
            VALUES (?, ?, ?, ?)
        """, rows)
        self.store._conn.commit()

        df = pd.DataFrame([{
            "open": float(k[1]), "high": float(k[2]), "low": float(k[3]),
            "close": float(k[4]), "volume": float(k[5]),
        } for k in klines])
        df = _compute_technicals(df)

        tech_rows = []
        for i, k in enumerate(klines):
            ts = float(k[0]) / 1000.0
            for col in df.columns:
                if col not in ("open", "high", "low", "close", "volume"):
                    val = float(df.iloc[i][col]) if i < len(df) else 0.0
                    tech_rows.append((ts, ticker, col, val))

        if tech_rows:
            self.store._conn.executemany("""
                INSERT INTO features_computed (timestamp, ticker, feature_name, feature_value)
                VALUES (?, ?, ?, ?)
            """, tech_rows)
            self.store._conn.commit()

        total = len(rows) + len(tech_rows)
        logger.info(f"Fetched {len(klines)} klines + technicals for {ticker} from Binance REST")
        return total
