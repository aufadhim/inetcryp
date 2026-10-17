"""Public Binance OHLCV only. Bounded pagination, immutable interval cache."""
import hashlib
import re
import time
from pathlib import Path
import numpy as np
import pandas as pd
import requests


def historical(symbol, start, end, cache_dir="data/research/cache", interval="15m"):
    if not re.fullmatch(r"[A-Z0-9]{3,20}", symbol):
        raise ValueError("Invalid symbol")
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    start = start.tz_localize("UTC") if start.tzinfo is None else start.tz_convert("UTC")
    end = end.tz_localize("UTC") if end.tzinfo is None else end.tz_convert("UTC")
    intervals = {"15m": (pd.Timedelta(minutes=15), "15min", 900000),
                 "1h": (pd.Timedelta(hours=1), "1h", 3600000),
                 "4h": (pd.Timedelta(hours=4), "4h", 14400000)}
    if interval not in intervals:
        raise ValueError("Unsupported historical interval")
    step, frequency, step_ms = intervals[interval]
    if start != start.floor(frequency) or end != end.floor(frequency) or not start < end:
        raise ValueError("Require aligned, ascending UTC interval")
    if end > pd.Timestamp.now(tz="UTC").floor(frequency):
        raise ValueError("Cannot fetch unfinished candles")
    path = Path(cache_dir) / f"{symbol}-{interval}-{start.value}-{end.value}.json"
    if path.exists():
        frame = pd.read_json(path, orient="table")
    else:
        rows, cursor = [], int(start.timestamp()*1000)
        end_ms = int(end.timestamp()*1000)
        session = requests.Session()  # deliberately no application client or credentials
        while cursor < end_ms:
            response = session.get("https://data-api.binance.vision/api/v3/klines",
                params={"symbol": symbol, "interval": interval, "startTime": cursor,
                        "endTime": end_ms-1, "limit": 1000}, timeout=30)
            if response.status_code in (418, 429):
                raise RuntimeError("Public API rate limit; stop and retry later")
            response.raise_for_status()
            batch = response.json()
            if not batch or int(batch[-1][0])+step_ms <= cursor:
                raise ValueError("Missing history or pagination did not advance")
            rows.extend(batch)
            cursor = int(batch[-1][0])+step_ms
            time.sleep(0.1)
        frame = pd.DataFrame({"Open": [float(x[1]) for x in rows],
            "High": [float(x[2]) for x in rows], "Low": [float(x[3]) for x in rows],
            "Close": [float(x[4]) for x in rows], "Volume": [float(x[5]) for x in rows]},
            index=pd.to_datetime([x[0] for x in rows], unit="ms", utc=True))
    frame.index = frame.index.as_unit("ns")
    expected = pd.date_range(start, end, freq=frequency, inclusive="left")
    if not frame.index.equals(expected) or not np.isfinite(frame.to_numpy()).all():
        raise ValueError("Missing/duplicate/out-of-order/non-finite candles; dataset rejected")
    if (frame[["Open", "High", "Low", "Close"]] <= 0).any().any() or (frame.Volume < 0).any():
        raise ValueError("Invalid OHLCV values")
    if ((frame.High < frame[["Open", "Close", "Low"]].max(axis=1)) |
        (frame.Low > frame[["Open", "Close", "High"]].min(axis=1))).any():
        raise ValueError("Invalid candle range")
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        frame.to_json(temp, orient="table", date_format="iso", double_precision=15)
        temp.replace(path)
    return frame, {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                   "bars": len(frame), "start": start.isoformat(), "end_exclusive": end.isoformat()}
