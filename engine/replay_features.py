"""Exact last-two-row technical features for the paper engine's 200-bar window.

No whale features are needed for new EMA-only positions. EMA seed correction
preserves rolling-window behavior rather than silently using full-history EMAs.
"""
import numpy as np
import pandas as pd


class ReplayFeatures:
    def __init__(self, frame):
        self.frame = frame
        close = frame.Close
        self.values = frame[["Close", "Low"]].copy()
        for span in (9, 21, 50):
            self.values[f"EMA{span}"] = close.ewm(span=span, adjust=False).mean()
        tr = pd.concat([frame.High-frame.Low, (frame.High-close.shift()).abs(),
                        (frame.Low-close.shift()).abs()], axis=1).max(axis=1)
        self.values["ATR14"] = tr.rolling(14).mean()
        up_move = frame.High.diff()
        down_move = -frame.Low.diff()
        plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=frame.index)
        minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=frame.index)
        tr_sum = tr.rolling(14).sum().replace(0, np.nan)
        plus_di = 100 * plus_dm.rolling(14).sum() / tr_sum
        minus_di = 100 * minus_dm.rolling(14).sum() / tr_sum
        dx = 100 * (plus_di-minus_di).abs() / (plus_di+minus_di).replace(0, np.nan)
        self.values["ADX14"] = dx.rolling(14).mean()
        self.values["ATR_PCT"] = self.values["ATR14"] / close.replace(0, np.nan) * 100
        gains = close.diff().clip(lower=0).rolling(14).mean()
        losses = (-close.diff().clip(upper=0)).rolling(14).mean().replace(0, np.nan)
        self.values["RSI14"] = (100-100/(1+gains/losses)).fillna(50)
        self.values.loc[losses.isna() & (gains > 0), "RSI14"] = 100
        self.values["RelativeVolume"] = frame.Volume / frame.Volume.shift().rolling(20).mean().replace(0, np.nan)
        self.array = self.values.to_numpy(copy=True)
        self.columns = list(self.values.columns)

    def at(self, cursor):
        if cursor < 100:
            raise ValueError("100 closed bars required")
        start = max(0, cursor-200)
        rows = self.array[cursor-2:cursor].copy()
        for span in (9, 21, 50):
            col = self.columns.index(f"EMA{span}")
            difference = self.array[start, 0]-self.array[start, col]
            decay = 1-2/(span+1)
            rows[0, col] += decay**(cursor-2-start)*difference
            rows[1, col] += decay**(cursor-1-start)*difference
        # The rule reads only the last two rows and checks a 100-bar warmup.
        values = np.full((100, len(self.columns)), np.nan)
        values[-2:] = rows
        return pd.DataFrame(values, index=self.frame.index[cursor-100:cursor], columns=self.columns)
