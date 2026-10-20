"""Bounded autonomous research and isolated paper tournament. No order API."""
from __future__ import annotations
import hashlib
import json
import math
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd

VERSION = "lab_v1"
FAMILIES = ("ema_pullback", "channel_breakout", "rsi_reversion", "vwap_reclaim", "flow_breakout", "compression")


@dataclass(frozen=True)
class Candidate:
    family: str
    stop_pct: float = 1.5
    target_pct: float = 3.0
    hold_bars: int = 16
    volume_ratio: float = 1.2

    @property
    def id(self):
        raw = json.dumps({"version": VERSION, **asdict(self)}, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def validate(self):
        if (self.family not in FAMILIES or not 0.5 <= self.stop_pct <= 3
                or not 1 <= self.target_pct <= 8 or not 4 <= self.hold_bars <= 48
                or not 1 <= self.volume_ratio <= 3 or type(self.hold_bars) is not int):
            raise ValueError("Candidate outside approved research bounds")
        return self


def candidates():
    # Freeze this small search before any dataset/holdout is observed.
    return [Candidate(family, stop, target).validate() for family in FAMILIES
            for stop, target in ((1.5, 3.0), (1.0, 2.0))]


class Registry:
    def __init__(self, path="data/lab/registry.sqlite"):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=30)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT, payload TEXT, PRIMARY KEY(kind,id))")
        self.db.execute("CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY, at TEXT, event TEXT, payload TEXT)")
        self.db.commit()

    def get(self, kind, key, default=None):
        row = self.db.execute("SELECT payload FROM records WHERE kind=? AND id=?", (kind, key)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, kind, key, value):
        self.db.execute("INSERT OR REPLACE INTO records VALUES (?,?,?)", (kind, key, json.dumps(value, allow_nan=False)))
        self.db.commit()

    def event(self, event, payload):
        self.db.execute("INSERT INTO events(at,event,payload) VALUES (?,?,?)",
                        (datetime.now(timezone.utc).isoformat(), event, json.dumps(payload, allow_nan=False)))
        self.db.commit()


def features(frame):
    if not isinstance(frame.index, pd.DatetimeIndex) or not frame.index.is_monotonic_increasing or frame.index.has_duplicates:
        raise ValueError("Ascending unique timestamps required")
    cols = ["Open", "High", "Low", "Close", "Volume"]
    if not np.isfinite(frame[cols].to_numpy()).all() or (frame[cols[:4]] <= 0).any().any() or (frame.Volume < 0).any():
        raise ValueError("Invalid OHLCV")
    if ((frame.High < frame[["Open", "Close", "Low"]].max(axis=1)) | (frame.Low > frame[["Open", "Close", "High"]].min(axis=1))).any():
        raise ValueError("Invalid candle range")
    f = frame.copy()
    c = f.Close
    for n in (9, 21, 50):
        f[f"ema{n}"] = c.ewm(span=n, adjust=False).mean()
    f["rvol"] = f.Volume / f.Volume.shift().rolling(20).mean().replace(0, np.nan)
    gain, loss = c.diff().clip(lower=0).rolling(14).mean(), -c.diff().clip(upper=0).rolling(14).mean()
    f["rsi"] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    f.loc[(loss == 0) & (gain > 0), "rsi"] = 100
    f["hi"] = f.High.shift().rolling(20).max()
    f["lo"] = f.Low.shift().rolling(20).min()
    f["width"] = (f.hi - f.lo) / c
    f["vwap"] = ((c * f.Volume).rolling(20).sum() / f.Volume.rolling(20).sum().replace(0, np.nan))
    f["flow"] = (((2*c-f.High-f.Low)/(f.High-f.Low).replace(0,np.nan))*f.Volume).rolling(20).sum()
    return f


def signals(f, candidate):
    candidate.validate()
    trend = (f.ema21 > f.ema50) & (f.ema50 > f.ema50.shift(3))
    volume = f.rvol >= candidate.volume_ratio
    rules = {
        "ema_pullback": trend & (f.Low.shift() <= f.ema9.shift()) & (f.Close > f.ema9) & f.rsi.between(45, 68),
        "channel_breakout": trend & (f.Close > f.hi),
        "rsi_reversion": (f.rsi.shift() < 30) & (f.rsi >= 30) & (f.Close > f.Close.shift()) & (f.Close > f.ema50*0.95),
        "vwap_reclaim": trend & (f.Close.shift() <= f.vwap.shift()) & (f.Close > f.vwap),
        "flow_breakout": trend & (f.flow > 0) & (f.Close > f.hi) & (f.rvol >= 1.8),
        "compression": (f.width.shift() < 0.05) & (f.Close > f.hi) & (f.flow > 0),
    }
    return (rules[candidate.family] & volume).fillna(False).to_numpy()


def account():
    return {"cash": 1000.0, "positions": {}, "trades": [], "peak": 1000.0, "max_drawdown_pct": 0.0,
            "equity": 1000.0, "seen": {}, "first_at": None, "last_at": None,"observed_steps":0}


def advance(state, candidate, bars, entries, stamp, fee=0.001, slip=0.0005, allow_entry=True):
    """Same execution for historical and forward paper: prior close signal, next open fill.

    Completed bars only; adverse opening gaps honored; stop wins ambiguous bars.
    Each position limited to $50 with at most 5 open positions; no leverage.
    """
    candidate.validate()
    now = pd.Timestamp(stamp)
    if not bars or all(state["seen"].get(s)==now.isoformat() for s in bars):
        return state
    if state["last_at"] != now.isoformat():
        state["observed_steps"] = state.get("observed_steps",0)+1
    state["first_at"] = state["first_at"] or now.isoformat()
    for symbol in sorted(bars):
        bar = bars[symbol]
        if state["seen"].get(symbol) == now.isoformat():
            continue
        state["seen"][symbol] = now.isoformat()
        pos = state["positions"].get(symbol)
        opened = False
        daily = sum(t["pnl_usd"] for t in state["trades"] if t["exit_time"][:10] == now.isoformat()[:10])
        if (not pos and entries.get(symbol) and allow_entry and daily > -10
                and len(state["positions"]) < 5 and state["cash"] >= 50):
            price = float(bar["Open"])*(1+slip)
            pos = {"entry": price, "quantity": 50/(1+fee)/price, "size": 50,
                   "entry_time": now.isoformat(), "age": 0}
            state["positions"][symbol] = pos
            state["cash"] -= 50
            opened = True
        if pos:
            pos["age"] += 1
            stop, target = pos["entry"]*(1-candidate.stop_pct/100), pos["entry"]*(1+candidate.target_pct/100)
            op, low, high, close = (float(bar[k]) for k in ("Open", "Low", "High", "Close"))
            price, reason = None, None
            if not opened and op <= stop:
                price, reason = op, "gap_stop"
            elif low <= stop:
                price, reason = stop, "stop"
            elif high >= target:
                price, reason = target, "target"
            elif pos["age"] >= candidate.hold_bars:
                price, reason = close, "time_stop"
            if price is not None:
                proceeds = pos["quantity"]*price*(1-slip)*(1-fee)
                state["cash"] += proceeds
                state["trades"].append({"symbol": symbol, "strategy": candidate.id, "entry_time": pos["entry_time"],
                    "exit_time": now.isoformat(), "pnl_usd": proceeds-pos["size"], "reason": reason})
                del state["positions"][symbol]
            else:
                pos["mark"] = close
    equity = state["cash"] + sum(p["quantity"]*p.get("mark",p["entry"])*(1-slip)*(1-fee) for p in state["positions"].values())
    state["equity"] = equity
    state["peak"] = max(state["peak"], equity)
    state["max_drawdown_pct"] = max(state["max_drawdown_pct"], (state["peak"]-equity)/state["peak"]*100)
    state["last_at"] = now.isoformat()
    return state


def stats(state):
    trades = state["trades"]
    wins = sum(t["pnl_usd"] > 0 for t in trades)
    gain = sum(max(0,t["pnl_usd"]) for t in trades)
    loss = -sum(min(0,t["pnl_usd"]) for t in trades)
    return {"equity": round(state["equity"],4), "net_pnl": state["equity"]-1000,
        "trades": len(trades), "win_rate": wins/len(trades)*100 if trades else 0,
        "profit_factor": gain/loss if loss else (999 if gain else 0),
        "expectancy": sum(t["pnl_usd"] for t in trades)/len(trades) if trades else 0,
        "max_drawdown_pct": state["max_drawdown_pct"], "open_positions": len(state["positions"])}


def simulate(frames, candidate, start, end, cost=1):
    state = account()
    prepared = {s: (f, signals(f,candidate), {t:i for i,t in enumerate(f.index)},
                    f[["Open","High","Low","Close"]].to_numpy()) for s,f in frames.items()}
    timeline = sorted(set(t for f in frames.values() for t in f.index if start <= t < end))
    for t in timeline:
        bars, entries = {}, {}
        for s,(f,mask,locations,values) in prepared.items():
            if t not in locations:
                continue
            i = locations[t]
            if i < 100:
                continue
            bars[s], entries[s] = dict(zip(("Open","High","Low","Close"),values[i])), bool(mask[i-1])
        advance(state,candidate,bars,entries,t,fee=0.001*cost,slip=0.0005*cost)
    return stats(state)


def research_gate(validation, stress, holdout, folds, symbol_results):
    reasons = []
    for name, result in (("validation",validation),("double_cost",stress),("holdout",holdout)):
        if result["net_pnl"] <= 0 or result["expectancy"] <= 0 or result["profit_factor"] < 1.3:
            reasons.append(name+": insufficient net edge")
        if result["trades"] < 30 or result["max_drawdown_pct"] > 5:
            reasons.append(name+": insufficient sample or excessive drawdown")
    if len(folds) < 3 or sum(r["net_pnl"] > 0 for r in folds) < 2:
        reasons.append("walk_forward: fewer than two positive folds")
    if len(symbol_results) < 3 or sum(r["net_pnl"] > 0 for r in symbol_results) < 3:
        reasons.append("cross_coin: require three profitable symbols")
    return {"eligible": not reasons, "reasons": reasons}


def forward_gate(state):
    result = stats(state)
    days = (pd.Timestamp(state["last_at"])-pd.Timestamp(state["first_at"])).total_seconds()/86400 if state["first_at"] else 0
    result["days"] = days
    expected = int(days*96)+1
    result["coverage"] = min(1,state.get("observed_steps",0)/expected)
    symbol_pnl = {}
    for trade in state["trades"]:
        symbol_pnl[trade["symbol"]] = symbol_pnl.get(trade["symbol"],0) + trade["pnl_usd"]
    result["profitable_symbols"] = sum(pnl>0 for pnl in symbol_pnl.values())
    result["eligible"] = (days >= 30 and result["trades"] >= 200 and result["profit_factor"] >= 1.3
        and result["max_drawdown_pct"] <= 5 and result["expectancy"] > 0 and result["net_pnl"] > 0
        and result["profitable_symbols"] >= 3 and result["coverage"] >= .95)
    return result
