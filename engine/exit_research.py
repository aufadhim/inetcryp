"""Paired exit diagnostics, not a portfolio backtest or admission decision."""
import pandas as pd
from engine.research_lab import account, advance, signals

POLICIES=("fixed","sl_plus","trailing")


def paired_exits(frames,candidate,start,end,cost=1,delay_bars=0):
    rows=[]
    for symbol,frame in sorted(frames.items()):
        cohorts=0
        mask=signals(frame,candidate)
        reserved_until=-1
        for i in range(100+delay_bars,len(frame)):
            t=frame.index[i]
            if not start<=t<end or i<=reserved_until or not mask[i-1-delay_bars]:continue
            # Reserve the full holding window regardless of any variant's early exit.
            # Thus every variant receives precisely the same entries and no re-entry advantage.
            stop_i=i+candidate.hold_bars
            if stop_i>len(frame) or frame.index[stop_i-1]>=end:continue
            volume=float(frame.iloc[i-1].Close*frame.iloc[i-1].Volume)
            if volume<=0 or 50/volume>.001:continue
            if cohorts>=60:break
            cohorts+=1
            reserved_until=stop_i-1
            states={p:account() for p in POLICIES}
            for j in range(i,stop_i):
                candle=frame.iloc[j]
                bar={k:float(candle[k]) for k in ("Open","High","Low","Close")}
                bar["decision_quote_volume"]=float(frame.iloc[j-1].Close*frame.iloc[j-1].Volume)
                for policy,state in states.items():
                    if j>i and not state["positions"]:continue
                    advance(state,candidate,{symbol:bar},{symbol:j==i},frame.index[j],
                            fee=.001*cost,slip=.0005*cost,spread=.0005*cost,
                            track_curve=False,cost_guard=True,exit_policy=policy)
            if not all(s["trades"] for s in states.values()):continue
            rows.append({"symbol":symbol,"entry_time":t.isoformat(),
                         "regime":str(frame.iloc[i-1].regime),
                         "pnl":{p:s["trades"][0]["pnl_usd"] for p,s in states.items()}})
    totals={p:{"net_pnl_sum":sum(r["pnl"][p] for r in rows),"trades":len(rows),
               "wins":sum(r["pnl"][p]>0 for r in rows),
               "delta_vs_fixed":sum(r["pnl"][p]-r["pnl"]["fixed"] for r in rows)} for p in POLICIES}
    regimes={regime:{p:sum(r["pnl"][p] for r in rows if r["regime"]==regime) for p in POLICIES}
             for regime in sorted({r["regime"] for r in rows})}
    return {"policies":totals,"by_regime":regimes,"pairs":rows,
            "scope":"Paired $50 independent trades; NOT portfolio return; no portfolio daily-loss gate or cross-symbol exposure simulation",
            "paper_admission":False,"max_cohorts_per_symbol":60,"activation_pct":.8,"net_lock_pct":.1,"trailing_distance_pct":.6}
