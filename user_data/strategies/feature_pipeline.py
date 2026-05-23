import numpy as np
import pandas as pd
from typing import Any, Tuple, Optional


def compute_sentiment_features(
    text: str,
    analyzer: Any,
) -> np.ndarray:
    result = analyzer.analyze(text)
    return analyzer.to_feature_vector(result)


def compute_sentiment_features_from_dict(
    result: dict[str, float],
    analyzer: Any,
) -> np.ndarray:
    return analyzer.to_feature_vector(result)


# ── Advanced Feature Engineering (Stock-return-predictor enriched) ──

def compute_momentum_features(close: pd.Series) -> pd.DataFrame:
    df = pd.DataFrame(index=close.index, dtype=np.float32)
    for p in [1, 2, 3, 5, 10, 21, 63]:
        df[f"mom_ret_{p}d"] = close.pct_change(p).fillna(0).astype(np.float32)
    for p in [5, 10, 21, 63]:
        ma = close.rolling(p).mean().fillna(close)
        df[f"mom_ma_ratio_{p}d"] = (close / ma - 1).fillna(0).astype(np.float32)
    return df


def compute_volatility_features(close: pd.Series, high: pd.Series, low: pd.Series) -> pd.DataFrame:
    df = pd.DataFrame(index=close.index, dtype=np.float32)
    ret = close.pct_change().fillna(0)
    for p in [5, 10, 21, 63]:
        df[f"vol_realized_{p}d"] = ret.rolling(p).std().fillna(0).astype(np.float32)
        downside = ret[ret < 0].rolling(p).std().fillna(0)
        upside = ret[ret > 0].rolling(p).std().fillna(0)
        df[f"vol_downside_{p}d"] = downside.astype(np.float32)
        df[f"vol_upside_{p}d"] = upside.astype(np.float32)
    df["vol_skew_21d"] = (
        df["vol_downside_21d"] / (df["vol_upside_21d"] + 1e-8) - 1
    ).fillna(0).astype(np.float32)
    typical = (high + low + close) / 3
    df["atr_14"] = typical.diff().abs().rolling(14).mean().fillna(0).astype(np.float32)
    df["atr_pct"] = (df["atr_14"] / close).fillna(0).astype(np.float32)
    df["vol_regime"] = pd.qcut(
        df["vol_realized_21d"].rank(method="first"),
        q=[0, 0.33, 0.67, 1.0], labels=[0, 1, 2], duplicates="drop",
    ).astype(float).fillna(1).astype(np.float32)
    return df


def compute_mean_reversion_features(close: pd.Series, high: pd.Series, low: pd.Series) -> pd.DataFrame:
    df = pd.DataFrame(index=close.index, dtype=np.float32)
    for p in [5, 14, 21]:
        ma = close.rolling(p).mean()
        std = close.rolling(p).std()
        df[f"bb_pct_b_{p}"] = ((close - ma) / (2 * std + 1e-8)).fillna(0).astype(np.float32)
        df[f"bb_width_{p}"] = (2 * std / ma).fillna(0).astype(np.float32)
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / (loss + 1e-8)
    df["rsi_14"] = (100 - 100 / (1 + rs)).fillna(50).astype(np.float32)
    df["rsi_regime"] = pd.cut(
        df["rsi_14"], bins=[0, 30, 70, 100], labels=[-1, 0, 1],
    ).astype(float).fillna(0).astype(np.float32)
    fast_ma = close.ewm(span=12).mean()
    slow_ma = close.ewm(span=26).mean()
    df["macd"] = (fast_ma - slow_ma).fillna(0).astype(np.float32)
    df["macd_signal"] = df["macd"].ewm(span=9).mean().fillna(0).astype(np.float32)
    df["macd_hist"] = (df["macd"] - df["macd_signal"]).fillna(0).astype(np.float32)
    df["stoch_k_14"] = ((close - low.rolling(14).min()) / (high.rolling(14).max() - low.rolling(14).min() + 1e-8) * 100).fillna(50).astype(np.float32)
    return df


def compute_volume_features(close: pd.Series, volume: pd.Series) -> pd.DataFrame:
    df = pd.DataFrame(index=close.index, dtype=np.float32)
    df["volume_zscore_21"] = ((volume - volume.rolling(21).mean()) / (volume.rolling(21).std() + 1e-8)).fillna(0).astype(np.float32)
    for p in [5, 10, 21]:
        df[f"volume_ma_ratio_{p}d"] = (volume / volume.rolling(p).mean()).fillna(1).astype(np.float32)
    obv = (volume * ((close.diff() > 0).astype(int) * 2 - 1)).cumsum()
    df["obv_ma_ratio_21"] = (obv / obv.rolling(21).mean()).fillna(1).astype(np.float32)
    return df


def compute_calendar_features(index: pd.DatetimeIndex) -> pd.DataFrame:
    df = pd.DataFrame(index=index, dtype=np.float32)
    df["day_of_week"] = index.dayofweek.astype(np.float32)
    df["month"] = index.month.astype(np.float32)
    df["quarter"] = index.quarter.astype(np.float32)
    for d in range(5):
        df[f"dow_{d}"] = (df["day_of_week"] == d).astype(np.float32)
    return df


def compute_advanced_features(ohlcv: pd.DataFrame) -> pd.DataFrame:
    close = ohlcv["Close"] if "Close" in ohlcv else ohlcv["close"]
    high = ohlcv["High"] if "High" in ohlcv else ohlcv["high"]
    low = ohlcv["Low"] if "Low" in ohlcv else ohlcv["low"]
    volume = ohlcv["Volume"] if "Volume" in ohlcv else ohlcv["volume"]
    feats = [compute_momentum_features(close)]
    feats.append(compute_volatility_features(close, high, low))
    feats.append(compute_mean_reversion_features(close, high, low))
    feats.append(compute_volume_features(close, volume))
    if isinstance(ohlcv.index, pd.DatetimeIndex):
        feats.append(compute_calendar_features(ohlcv.index))
    result = pd.concat(feats, axis=1)
    result.fillna(0.0, inplace=True)
    return result.astype(np.float32)


def compute_order_imbalance(
    bid_volumes: np.ndarray, ask_volumes: np.ndarray
) -> np.ndarray:
    bid = np.float32(bid_volumes)
    ask = np.float32(ask_volumes)
    denom = bid + ask
    denom = np.where(denom == 0.0, 1.0, denom)
    return np.float32((bid - ask) / denom)


def compute_order_imbalance_from_frame(df: pd.DataFrame) -> pd.Series:
    bid = df["bid_volume"].to_numpy(dtype=np.float32)
    ask = df["ask_volume"].to_numpy(dtype=np.float32)
    denom = bid + ask
    denom = np.where(denom == 0.0, 1.0, denom)
    oi = np.float32((bid - ask) / denom)
    return pd.Series(oi, index=df.index, dtype=np.float32, name="oi")


def compute_trade_imbalance(
    trades: pd.DataFrame,
    price_col: str = "price",
    volume_col: str = "volume",
    side_col: str = "side",
    windows: list[str] = ["5min", "15min", "30min"],
) -> pd.DataFrame:
    df = trades.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)

    buy_vol = df[df[side_col] == "BUY"][volume_col].astype(np.float32)
    sell_vol = df[df[side_col] == "SELL"][volume_col].astype(np.float32)
    net_volume = buy_vol.sub(sell_vol, fill_value=0.0).astype(np.float32)

    ti = pd.DataFrame(index=df.index, dtype=np.float32)
    for w in windows:
        ti[f"ti_{w}"] = net_volume.rolling(w).sum().astype(np.float32)
    return ti


def ternary_agreement_model(
    btc_returns: pd.Series,
    alt_returns: pd.Series,
    lag: int = 5,
    threshold: float = 0.001,
    alt_name: str = "alt",
) -> pd.DataFrame:
    btc_lagged = btc_returns.shift(lag).rename("btc_lag")
    aligned = pd.concat([btc_lagged, alt_returns.rename(alt_name)], axis=1).dropna()

    btc_sign = np.sign(aligned["btc_lag"].to_numpy(dtype=np.float32))
    alt_sign = np.sign(aligned[alt_name].to_numpy(dtype=np.float32))

    ternary = np.where(
        btc_sign == alt_sign,
        np.where(btc_sign != 0, np.int8(1), np.int8(0)),
        np.where(
            (np.abs(aligned["btc_lag"].to_numpy()) > threshold)
            | (np.abs(aligned[alt_name].to_numpy()) > threshold),
            np.int8(-1),
            np.int8(0),
        ),
    )

    df = pd.DataFrame(index=aligned.index)
    df["tam_state"] = pd.Series(ternary, dtype=np.int8)
    df["tam_agreement"] = (ternary == 1).astype(np.int8)
    df["tam_disagreement"] = (ternary == -1).astype(np.int8)
    df["tam_strength"] = pd.Series(
        np.abs(aligned["btc_lag"].to_numpy(dtype=np.float32)), dtype=np.float32
    )
    return df


def optimal_tam_lag(
    btc_returns: pd.Series,
    alt_returns: pd.Series,
    max_lag: int = 20,
    threshold: float = 0.001,
) -> Tuple[int, float]:
    best_lag = 0
    best_score = -1.0
    for lag in range(1, max_lag + 1):
        btc_lagged = btc_returns.shift(lag)
        aligned = pd.concat([btc_lagged, alt_returns], axis=1).dropna().to_numpy()
        btc_s = np.sign(aligned[:, 0])
        alt_s = np.sign(aligned[:, 1])
        score = float(np.mean(btc_s == alt_s))
        if score > best_score:
            best_score = score
            best_lag = lag
    return best_lag, best_score


def polymarket_time_to_resolution(
    timestamps: pd.Series, expiration: pd.Timestamp
) -> pd.Series:
    total_seconds = (expiration - timestamps).dt.total_seconds().astype(np.float32)
    result = np.float32(total_seconds.to_numpy())
    result = np.clip(result, 0.0, None)
    result = result / np.float32(86400.0)
    return pd.Series(
        np.float32(result),
        index=timestamps.index,
        dtype=np.float32,
        name="ttr_days",
    )


def polymarket_time_decay_weight(
    timestamps: pd.Series, expiration: pd.Timestamp, decay_half_life_days: float = 7.0
) -> pd.Series:
    days = polymarket_time_to_resolution(timestamps, expiration)
    lam = np.float32(np.log(2) / decay_half_life_days)
    return pd.Series(
        np.float32(np.exp(-lam * days.to_numpy())),
        index=timestamps.index,
        dtype=np.float32,
        name="ttr_decay",
    )


def compute_microstructure_features(df: pd.DataFrame) -> pd.DataFrame:
    features = pd.DataFrame(index=df.index, dtype=np.float32)

    features["oi"] = compute_order_imbalance_from_frame(df)

    bid = df["bid_price"].to_numpy(dtype=np.float32)
    ask = df["ask_price"].to_numpy(dtype=np.float32)
    mid = (bid + ask) / np.float32(2.0)
    spread = np.where(mid > 0, (ask - bid) / mid, np.float32(0.0))
    features["mid_price"] = pd.Series(mid, dtype=np.float32)
    features["spread_bps"] = pd.Series(spread * 10000, dtype=np.float32)

    for w in [5, 15, 30]:
        features[f"oi_ma_{w}"] = (
            features["oi"].rolling(w, min_periods=1).mean().astype(np.float32)
        )
        features[f"spread_ma_{w}"] = (
            features["spread_bps"].rolling(w, min_periods=1).mean().astype(np.float32)
        )

    features["log_mid"] = pd.Series(
        np.where(mid > 0, np.log(mid), np.float32(0.0)),
        dtype=np.float32,
    )
    features["returns"] = features["log_mid"].diff().fillna(0.0).astype(np.float32)

    features.fillna(0.0, inplace=True)
    return features


def resample_ticks_to_ohlcv(
    ticks: pd.DataFrame,
    freq: str = "1min",
    price_col: str = "price",
    volume_col: str = "volume",
) -> pd.DataFrame:
    if not isinstance(ticks.index, pd.DatetimeIndex):
        ticks = ticks.copy()
        ticks.index = pd.to_datetime(ticks.index)
    ohlc = ticks[price_col].resample(freq).ohlc()
    ohlc.columns = [f"{c}".lower() for c in ohlc.columns]
    ohlc["volume"] = ticks[volume_col].resample(freq).sum().astype(np.float32)
    ohlc = ohlc.astype({c: np.float32 for c in ohlc.columns})
    return ohlc


def build_feature_matrix(
    lob_snapshots: pd.DataFrame,
    trades: Optional[pd.DataFrame] = None,
    btc_returns: Optional[pd.Series] = None,
    alt_returns: Optional[pd.Series] = None,
    expiration: Optional[pd.Timestamp] = None,
    alt_name: str = "alt",
    tam_lag: int = 5,
    tam_threshold: float = 0.001,
) -> pd.DataFrame:
    feats = compute_microstructure_features(lob_snapshots)

    if trades is not None and len(trades) > 0:
        ti = compute_trade_imbalance(trades)
        feats = feats.join(ti, how="left").fillna(0.0)

    if btc_returns is not None and alt_returns is not None:
        tam = ternary_agreement_model(
            btc_returns, alt_returns, lag=tam_lag, threshold=tam_threshold, alt_name=alt_name
        )
        feats = feats.join(tam, how="left").fillna(0.0)

    if expiration is not None:
        feats["ttr_days"] = polymarket_time_to_resolution(
            pd.Series(feats.index), expiration
        )
        feats["ttr_decay"] = polymarket_time_decay_weight(
            pd.Series(feats.index), expiration
        )

    return feats.astype(np.float32)
