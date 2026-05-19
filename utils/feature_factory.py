import numpy as np
import pandas as pd
from typing import Optional


class FeatureFactory:
    COLUMN_MAP = {
        "open": ["Open", "open", "OPEN"],
        "high": ["High", "high", "HIGH"],
        "low": ["Low", "low", "LOW"],
        "close": ["Close", "close", "CLOSE"],
        "volume": ["Volume", "volume", "VOLUME"],
    }

    def __init__(self, ohlcv: pd.DataFrame):
        self.df = ohlcv.copy()
        self._resolve_columns()
        self._compute_all()

    def _resolve_columns(self):
        for key, names in self.COLUMN_MAP.items():
            for n in names:
                if n in self.df.columns:
                    setattr(self, f"_{key}", self.df[n])
                    break
            else:
                setattr(self, f"_{key}", pd.Series(0.0, index=self.df.index))

    def _compute_all(self):
        self._momentum_features()
        self._volatility_features()
        self._mean_reversion_features()
        self._volume_features()
        self._microstructure_features()
        self._calendar_features()

    def _momentum_features(self):
        c = self._close
        for p in [1, 2, 3, 5, 10, 21]:
            self.df[f"ret_{p}d"] = c.pct_change(p).fillna(0)
        for p in [5, 10, 21]:
            ma = c.rolling(p).mean().fillna(c)
            self.df[f"ma_{p}d"] = ma
            self.df[f"ma_ratio_{p}d"] = (c / ma - 1).fillna(0)
        self.df["mom_12m"] = c.pct_change(252).fillna(0)

    def _volatility_features(self):
        c = self._close
        h = self._high
        l = self._low
        ret = c.pct_change().fillna(0)
        for p in [5, 10, 21, 63]:
            self.df[f"realized_vol_{p}d"] = ret.rolling(p).std().fillna(0)
            self.df[f"downside_vol_{p}d"] = ret[ret < 0].rolling(p).std().fillna(0)
            self.df[f"upside_vol_{p}d"] = ret[ret > 0].rolling(p).std().fillna(0)
        self.df["vol_skew_21d"] = (self.df["downside_vol_21d"] / (self.df["upside_vol_21d"] + 1e-8) - 1).fillna(0)
        typical = (h + l + c) / 3
        self.df["atr_14"] = typical.diff().abs().rolling(14).mean().fillna(0)
        self.df["atr_pct"] = (self.df["atr_14"] / c).fillna(0)
        v = self.df["realized_vol_21d"].rank(method="first")
        self.df["vol_regime"] = pd.qcut(v, q=[0, 0.33, 0.67, 1.0], labels=[0, 1, 2], duplicates="drop").astype(float).fillna(1)

    def _mean_reversion_features(self):
        c = self._close
        h = self._high
        l = self._low
        for p in [5, 14, 21]:
            ma = c.rolling(p).mean()
            std = c.rolling(p).std()
            self.df[f"bb_pct_b_{p}"] = ((c - ma) / (2 * std + 1e-8)).fillna(0)
            self.df[f"bb_width_{p}"] = (2 * std / ma).fillna(0)
        delta = c.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / (loss + 1e-8)
        self.df["rsi_14"] = (100 - 100 / (1 + rs)).fillna(50)
        fast_ma = c.ewm(span=12).mean()
        slow_ma = c.ewm(span=26).mean()
        self.df["macd"] = (fast_ma - slow_ma).fillna(0)
        self.df["macd_signal"] = self.df["macd"].ewm(span=9).mean().fillna(0)
        self.df["macd_hist"] = (self.df["macd"] - self.df["macd_signal"]).fillna(0)
        self.df["perc_k_14"] = ((c - l.rolling(14).min()) / (h.rolling(14).max() - l.rolling(14).min() + 1e-8) * 100).fillna(50)

    def _volume_features(self):
        v = self._volume
        c = self._close
        self.df["volume_zscore_21"] = ((v - v.rolling(21).mean()) / (v.rolling(21).std() + 1e-8)).fillna(0)
        for p in [5, 10, 21]:
            self.df[f"volume_ma_ratio_{p}d"] = (v / v.rolling(p).mean()).fillna(1)
        obv = (v * ((c.diff() > 0).astype(int) * 2 - 1)).cumsum()
        self.df["obv_ma_ratio_21"] = (obv / obv.rolling(21).mean()).fillna(1)

    def _microstructure_features(self):
        c = self._close
        h = self._high
        l = self._low
        o = self._open
        self.df["gap"] = (o / c.shift(1) - 1).fillna(0)
        self.df["intraday_range"] = ((h - l) / c).fillna(0)
        self.df["close_position"] = ((c - l) / (h - l + 1e-8)).fillna(0.5)

    def _calendar_features(self):
        if not isinstance(self.df.index, pd.DatetimeIndex):
            return
        self.df["day_of_week"] = self.df.index.dayofweek.astype(float)
        self.df["month"] = self.df.index.month.astype(float)
        for d in range(5):
            self.df[f"dow_{d}"] = (self.df["day_of_week"] == d).astype(float)

    def get_feature_names(self) -> list[str]:
        exclude = {"Open", "High", "Low", "Close", "Volume", "open", "high", "low", "close", "volume",
                   "OPEN", "HIGH", "LOW", "CLOSE", "VOLUME"}
        return [c for c in self.df.columns if c not in exclude]

    def get_feature_matrix(self) -> np.ndarray:
        return self.df[self.get_feature_names()].to_numpy(dtype=np.float32)

    def get_feature_dataframe(self) -> pd.DataFrame:
        return self.df[self.get_feature_names()]
