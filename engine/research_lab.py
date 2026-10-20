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

VERSION = "lab_v3"
FAMILIES = ("ema_pullback", "channel_breakout", "rsi_reversion", "vwap_reclaim", "flow_breakout", "compression")


@dataclass(frozen=True)
class Candidate:
    family: str
    stop_pct: float = 1.5
    target_pct: float = 3.0
    hold_bars: int = 16
    volume_ratio: float = 1.2
    regime_filter: str = "adaptive"

    @property
    def id(self):
        raw = json.dumps({"version": VERSION, **asdict(self)}, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def validate(self):
        if (self.family not in FAMILIES or not 0.5 <= self.stop_pct <= 3
                or not 1 <= self.target_pct <= 8 or not 4 <= self.hold_bars <= 48
                or not 1 <= self.volume_ratio <= 3 or type(self.hold_bars) is not int
                or self.regime_filter not in {"adaptive","off"}):
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
        self.db.execute("CREATE TABLE IF NOT EXISTS observation_points (source TEXT, symbol TEXT, event_at TEXT, received_at TEXT, payload TEXT, PRIMARY KEY(source,symbol,event_at))")
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

    def series(self, source, symbol, rows, time_field):
        received=datetime.now(timezone.utc).isoformat()
        before=self.db.total_changes
        for row in rows:
            try:
                at=datetime.fromtimestamp(float(row[time_field])/1000,timezone.utc).isoformat()
                self.db.execute("INSERT OR IGNORE INTO observation_points VALUES (?,?,?,?,?)",
                    (source,symbol,at,received,json.dumps(row,allow_nan=False)))
            except (KeyError,TypeError,ValueError,OverflowError):
                continue
        self.db.commit()
        return self.db.total_changes-before


def features(frame):
    if not isinstance(frame.index, pd.DatetimeIndex) or not frame.index.is_monotonic_increasing or frame.index.has_duplicates:
        raise ValueError("Ascending unique timestamps required")
    if frame.index.tz is None or (len(frame)>1 and not (frame.index.to_series().diff().iloc[1:]==pd.Timedelta(minutes=15)).all()):
        raise ValueError("Complete timezone-aware 15-minute candles required")
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
    tr=pd.concat([f.High-f.Low,(f.High-c.shift()).abs(),(f.Low-c.shift()).abs()],axis=1).max(axis=1)
    f["atr_pct"]=tr.rolling(14).mean()/c*100
    efficiency=(c-c.shift(20)).abs()/c.diff().abs().rolling(20).sum().replace(0,np.nan)
    f["regime"]=np.select([f.atr_pct>=3,(f.ema21>f.ema50)&(efficiency>=.3),
        (f.ema21<f.ema50)&(efficiency>=.3)], ["extreme","uptrend","downtrend"],default="range")
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
    regime_allowed=pd.Series(True,index=f.index)
    if candidate.regime_filter=="adaptive":
        regime_allowed=(f.regime=="range") if candidate.family=="rsi_reversion" else (f.regime=="uptrend")
        if candidate.family=="compression":regime_allowed=f.regime.isin(["range","uptrend"])
    return (rules[candidate.family] & volume & regime_allowed).fillna(False).to_numpy()


def account():
    return {"cash": 1000.0, "positions": {}, "trades": [], "peak": 1000.0, "max_drawdown_pct": 0.0,
            "equity": 1000.0, "seen": {}, "first_at": None, "last_at": None,"observed_steps":0,"equity_curve":[],"realized_days":{}}


def advance(state, candidate, bars, entries, stamp, fee=0.001, slip=0.0005, allow_entry=True, spread=0.0005, track_curve=True):
    """Same execution for historical and forward paper: prior close signal, next open fill.

    Completed bars only; adverse opening gaps honored; stop wins ambiguous bars.
    Each position limited to $50 with at most 5 open positions; no leverage.
    """
    candidate.validate()
    now = pd.Timestamp(stamp)
    if now.tzinfo is None:
        raise ValueError("Timezone required")
    now=now.tz_convert("UTC")
    now_iso=now.isoformat()
    if not bars or all(state["seen"].get(s,"")>=now_iso for s in bars):
        return state
    if state["last_at"] != now_iso:
        state["observed_steps"] = state.get("observed_steps",0)+1
    state["first_at"] = state["first_at"] or now_iso
    if "realized_days" not in state:
        state["realized_days"]={}
        for trade in state["trades"]:
            day=trade["exit_time"][:10]
            state["realized_days"][day]=state["realized_days"].get(day,0)+trade["pnl_usd"]
    day_key=now_iso[:10]
    for symbol in sorted(bars):
        bar = bars[symbol]
        seen=state["seen"].get(symbol)
        if seen and seen>=now_iso:
            continue
        state["seen"][symbol] = now_iso
        pos = state["positions"].get(symbol)
        opened = False
        quote_volume=bar.get("decision_quote_volume")
        liquidity_ok=quote_volume is None or (math.isfinite(float(quote_volume)) and float(quote_volume)>0 and 50/float(quote_volume)<=0.001)
        impact=0 if quote_volume is None or not liquidity_ok else 0.1*50/float(quote_volume)
        side_slip=slip+spread/2+impact
        daily = state["realized_days"].get(day_key,0)
        if (not pos and entries.get(symbol) and allow_entry and daily > -10 and liquidity_ok
                and len(state["positions"]) < 5 and state["cash"] >= 50):
            price = float(bar["Open"])*(1+side_slip)
            pos = {"entry": price, "quantity": 50/(1+fee)/price, "size": 50,
                   "entry_time": now_iso, "age": 0,"execution_slip":side_slip,
                   "reference_entry":float(bar["Open"]),"entry_regime":bar.get("decision_regime","unknown"),
                   "entry_hour_utc":now.hour,"entry_volatility":bar.get("decision_volatility","unknown"),
                   "entry_gap_pct":bar.get("entry_gap_pct"),"max_favorable_pct":0,"max_adverse_pct":0}
            state["positions"][symbol] = pos
            state["cash"] -= 50
            opened = True
        if pos:
            pos["age"] += 1
            stop, target = pos["entry"]*(1-candidate.stop_pct/100), pos["entry"]*(1+candidate.target_pct/100)
            op, low, high, close = (float(bar[k]) for k in ("Open", "Low", "High", "Close"))
            pos["max_favorable_pct"]=max(pos.get("max_favorable_pct",0),(high/pos["entry"]-1)*100)
            pos["max_adverse_pct"]=min(pos.get("max_adverse_pct",0),(low/pos["entry"]-1)*100)
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
                proceeds = pos["quantity"]*price*(1-max(side_slip,pos.get("execution_slip",slip)))*(1-fee)
                state["cash"] += proceeds
                state["trades"].append({"symbol": symbol, "strategy": candidate.id, "entry_time": pos["entry_time"],
                    "exit_time": now_iso, "pnl_usd": proceeds-pos["size"], "reason": reason,
                    "gross_pnl_usd":pos["size"]*(price/pos.get("reference_entry",pos["entry"])-1),
                    **{key:pos.get(key) for key in ("entry_regime","entry_hour_utc","entry_volatility","entry_gap_pct","max_favorable_pct","max_adverse_pct")},
                    "excursion_model":"candle_bounds_not_intrabar_path"})
                state["realized_days"][day_key]=state["realized_days"].get(day_key,0)+proceeds-pos["size"]
                del state["positions"][symbol]
            else:
                pos["mark"] = close
    equity = state["cash"] + sum(p["quantity"]*p.get("mark",p["entry"])*(1-max(slip,p.get("execution_slip",slip)))*(1-fee) for p in state["positions"].values())
    state["equity"] = equity
    state["peak"] = max(state["peak"], equity)
    state["max_drawdown_pct"] = max(state["max_drawdown_pct"], (state["peak"]-equity)/state["peak"]*100)
    state["last_at"] = now_iso
    if track_curve:
        curve=state.setdefault("equity_curve",[])
        point={"at":now_iso,"equity":equity}
        if curve and curve[-1]["at"]==point["at"]:
            curve[-1]=point
        else:
            curve.append(point)
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


def simulate(frames, candidate, start, end, cost=1, delay_bars=0, entry_masks=None, include_diagnostics=True):
    state = account()
    prepared = {s: (f, entry_masks[s] if entry_masks is not None else signals(f,candidate), {t:i for i,t in enumerate(f.index)},
                    f[["Open","High","Low","Close","Volume"]].to_numpy()) for s,f in frames.items()}
    contexts={s:(f.regime.to_numpy(),f.atr_pct.to_numpy()) for s,f in frames.items()}
    timeline = sorted(set(t for f in frames.values() for t in f.index if start <= t < end))
    for t in timeline:
        bars, entries = {}, {}
        for s,(f,mask,locations,values) in prepared.items():
            if t not in locations:
                continue
            i = locations[t]
            if i < 100:
                continue
            bars[s]=dict(zip(("Open","High","Low","Close"),values[i][:4]))
            bars[s]["decision_quote_volume"]=values[i-1][3]*values[i-1][4]
            bars[s]["decision_regime"]=str(contexts[s][0][i-1])
            atr=float(contexts[s][1][i-1])
            bars[s]["decision_volatility"]="high" if atr>=1.5 else "medium" if atr>=.5 else "low"
            bars[s]["entry_gap_pct"]=(values[i][0]/values[i-1][3]-1)*100
            entries[s]=bool(mask[max(0,i-1-delay_bars)])
        advance(state,candidate,bars,entries,t,fee=0.001*cost,slip=0.0005*cost,spread=.0005*cost,track_curve=False)
    result=stats(state)
    if include_diagnostics:
        from engine.research_analysis import diagnose
        result["diagnostics"]=diagnose(state["trades"])
    return result


def compare_forward(challenger, incumbent):
    """Compare marked daily returns over the same actually observed dates."""
    def daily(state):
        curve=state.get("equity_curve",[])
        if not curve: return pd.Series(dtype=float)
        s=pd.Series([p["equity"] for p in curve],index=pd.to_datetime([p["at"] for p in curve],utc=True))
        return s.resample("1D").last().pct_change(fill_method=None).dropna()
    paired=pd.concat([daily(challenger).rename("challenger"),daily(incumbent).rename("incumbent")],axis=1,sort=True).dropna()
    if len(paired)<30:
        return {"replace":False,"common_days":len(paired),"reason":"need_30_common_observed_days"}
    difference=(paired.challenger-paired.incumbent).to_numpy()
    # Bootstrap 5-day blocks, preserving short-range serial dependence.
    rng=np.random.default_rng(42)
    blocks=[difference[i:i+5] for i in range(0,len(difference)-4)]
    means=[]
    for _ in range(1000):
        sampled=np.concatenate([blocks[i] for i in rng.integers(0,len(blocks),size=math.ceil(len(difference)/5))])[:len(difference)]
        means.append(float(sampled.mean()))
    lower=float(np.quantile(means,.025))
    return {"replace":lower>0,"common_days":len(paired),"lower_daily_excess_return":lower,
            "mean_daily_excess_return":float(difference.mean()),"method":"five_day_block_bootstrap_1000"}


def holdout_watermark(reg):
    dates=[]
    for row in reg.db.execute("SELECT payload FROM records WHERE kind='experiment'"):
        data=json.loads(row[0])
        if data.get("status")=="completed" and data.get("holdout") is not None:
            dates.append(pd.Timestamp(data["end"]))
    return max(dates) if dates else None


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
        and result["profitable_symbols"] >= 3 and result["coverage"] >= .95
        and state.get("execution_model")=="observed_depth_v1" and state.get("valuation_complete",False))
    return result
