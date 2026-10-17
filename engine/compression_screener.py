"""Post-downtrend compression/base screener. Research watchlist, never an order signal."""
from __future__ import annotations

import concurrent.futures
import math
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from engine.binance_client import BinanceClient


def analyze_compression(symbol: str, frame: pd.DataFrame) -> Optional[Dict[str, Any]]:
    if frame is None or len(frame) < 100:
        return None
    data = frame.iloc[:-1].copy()  # never score the unfinished candle
    if len(data) < 99 or data[["Open", "High", "Low", "Close", "Volume"]].isna().any().any():
        return None

    base = data.iloc[-48:]
    recent = data.iloc[-12:]
    earlier = data.iloc[-48:-24]
    pre = data.iloc[-96:-48]
    close = float(data.Close.iloc[-1])
    pre_start = float(pre.Close.iloc[0])
    base_start = float(base.Close.iloc[0])
    downtrend_pct = (base_start / pre_start - 1) * 100 if pre_start else 0.0

    base_high, base_low = float(base.High.max()), float(base.Low.min())
    base_width = (base_high-base_low) / max(base_low, 1e-12) * 100
    early_width = (float(earlier.High.max())-float(earlier.Low.min())) / max(float(earlier.Low.min()), 1e-12) * 100
    recent_width = (float(recent.High.max())-float(recent.Low.min())) / max(float(recent.Low.min()), 1e-12) * 100
    contraction = recent_width / max(early_width, 1e-12)

    x = np.arange(len(recent), dtype=float)
    high_slope = float(np.polyfit(x, recent.High.to_numpy(float), 1)[0] / close * 100)
    low_slope = float(np.polyfit(x, recent.Low.to_numpy(float), 1)[0] / close * 100)
    resistance = float(data.High.iloc[-13:-1].max())
    support = float(data.Low.iloc[-13:-1].min())
    distance_to_breakout = (resistance-close) / max(close, 1e-12) * 100
    relative_volume = float(recent.Volume.iloc[-1] / max(data.Volume.iloc[-22:-2].mean(), 1e-12))
    volume_dryup = float(recent.Volume.mean() / max(earlier.Volume.mean(), 1e-12))
    cvd = float(recent["CVD_Delta"].sum()) if "CVD_Delta" in recent else 0.0

    post_downtrend = downtrend_pct <= -6.0
    stable_base = base_width <= 22.0
    narrowing = contraction <= 0.72 and high_slope <= 0.15 and low_slope >= -0.15
    near_edge = -2.0 <= distance_to_breakout <= 4.0
    if not (post_downtrend and stable_base and narrowing and near_edge):
        return None

    status = "WATCH_COMPRESSION"
    if close > resistance and relative_volume >= 1.35:
        status = "BREAKOUT_CONFIRMED"
    elif close < support and relative_volume >= 1.35:
        status = "BREAKDOWN"

    score = 50.0
    score += min(abs(downtrend_pct), 20) * 0.5
    score += max(0.0, (0.72-contraction) * 25)
    score += 8 if volume_dryup <= 0.85 else 0
    score += 8 if cvd > 0 else 0
    score += 10 if status == "BREAKOUT_CONFIRMED" else 0
    score -= 15 if status == "BREAKDOWN" else 0
    return {
        "symbol": symbol,
        "status": status,
        "score": round(max(0, min(100, score)), 1),
        "price": close,
        "downtrend_pct": round(downtrend_pct, 2),
        "base_width_pct": round(base_width, 2),
        "recent_width_pct": round(recent_width, 2),
        "contraction_ratio": round(contraction, 3),
        "distance_to_breakout_pct": round(distance_to_breakout, 2),
        "resistance": resistance,
        "support": support,
        "relative_volume": round(relative_volume, 2),
        "volume_dryup_ratio": round(volume_dryup, 2),
        "cvd_accumulation": cvd > 0,
        "note": "Watchlist only; wait for closed-candle breakout plus volume/retest."
    }


class CompressionScreener:
    def __init__(self, client: Optional[BinanceClient] = None):
        self.client = client or BinanceClient()

    def scan(self, timeframe: str = "4h", limit_symbols: int = 50) -> List[Dict[str, Any]]:
        tickers = self.client.get_top_tickers(limit=limit_symbols)
        def inspect(item):
            try:
                frame = self.client.get_klines(item["symbol"], timeframe, 180)
                return analyze_compression(item["symbol"], frame)
            except Exception:
                return None
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            for result in executor.map(inspect, tickers):
                if result:
                    results.append(result)
        priority = {"BREAKOUT_CONFIRMED": 0, "WATCH_COMPRESSION": 1, "BREAKDOWN": 2}
        return sorted(results, key=lambda row: (priority[row["status"]], -row["score"]))
