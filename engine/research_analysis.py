"""Descriptive loss attribution and frozen baseline comparisons."""
from collections import defaultdict
import math
from datetime import datetime, timezone


def diagnose(trades):
    trades=[dict(t) for t in trades]
    for t in trades:
        if "entry_hour_utc" not in t:
            try:t["entry_hour_utc"]=datetime.fromisoformat(t["entry_time"]).astimezone(timezone.utc).hour
            except (KeyError,ValueError,TypeError):pass
    dimensions={"symbol":"symbol","regime":"entry_regime","hour_utc":"entry_hour_utc",
                "volatility":"entry_volatility","exit_reason":"reason"}
    groups={}
    for name,field in dimensions.items():
        buckets=defaultdict(list)
        for trade in trades:buckets[str(trade.get(field,"unknown"))].append(trade)
        groups[name]={}
        for label,items in buckets.items():
            net=sum(t["pnl_usd"] for t in items)
            known=[t for t in items if "gross_pnl_usd" in t]
            gross=sum(t["gross_pnl_usd"] for t in known) if len(known)==len(items) else None
            groups[name][label]={"trades":len(items),"net_pnl":net,"gross_price_pnl":gross,
                "estimated_cost_drag":gross-net if gross is not None else None,"cost_coverage_trades":len(known),
                "win_rate":100*sum(t["pnl_usd"]>0 for t in items)/len(items),
                "expectancy":net/len(items),"sample_sufficient":len(items)>=20}
    cost_flips=sum(t.get("gross_pnl_usd",t["pnl_usd"])>0 and t["pnl_usd"]<=0 for t in trades)
    return {"groups":groups,"cost_flipped_winners":cost_flips,
        "interpretation":"Descriptive associations, not causal proof. Groups under 20 trades are weak evidence."}


def benchmark_gate(result, baselines):
    reasons=[]
    if result["net_pnl"]<=baselines["cash"]["net_pnl"]:reasons.append("did_not_beat_cash")
    if result["net_pnl"]<=baselines["ema_cross"]["net_pnl"]:reasons.append("did_not_beat_simple_ema")
    passive=baselines["buy_hold_capped"]
    if result["net_pnl"]<=passive["net_pnl"]:
        adjusted=result["net_pnl"]/max(.1,result["max_drawdown_pct"])
        passive_adjusted=passive["net_pnl"]/max(.1,passive["max_drawdown_pct"])
        if not (result["max_drawdown_pct"]<passive["max_drawdown_pct"]*.8 and adjusted>passive_adjusted):
            reasons.append("no_return_or_drawdown_advantage_over_capped_buy_hold")
    return {"eligible":not reasons,"reasons":reasons,
        "risk_basis":"Same $1,000 capital, $50 per position and $250 maximum gross exposure; realized risks can differ"}


def baselines(frames, start, end, cost_guard=False):
    from engine.research_lab import Candidate, simulate
    masks={symbol:((f.ema9>f.ema21)&(f.ema9.shift()<=f.ema21.shift())).fillna(False).to_numpy()
           for symbol,f in frames.items()}
    ema=simulate(frames,Candidate("ema_pullback"),start,end,entry_masks=masks,include_diagnostics=False,cost_guard=cost_guard)
    values=[]
    for symbol,f in sorted(frames.items()):
        subset=f.loc[(f.index>=start)&(f.index<end)]
        if not subset.empty:values.append((symbol,subset))
    values=values[:5]
    # Passive allocation uses the same cap, with costs on both entry and liquidation.
    curve={}
    for _,f in values:
        quantity=50/(1.001)/(float(f.iloc[0].Open)*1.00075)
        for stamp,row in f.iterrows():
            curve[stamp]=curve.get(stamp,0)+quantity*float(row.Close)*.99925*.999
    peak=1000;dd=0;equity=1000
    for stamp in sorted(curve):
        equity=1000-50*len(values)+curve[stamp]
        peak=max(peak,equity);dd=max(dd,(peak-equity)/peak*100)
    return {"cash":{"net_pnl":0,"max_drawdown_pct":0,"equity":1000},
            "buy_hold_capped":{"net_pnl":equity-1000,"equity":equity,"max_drawdown_pct":dd,
                               "symbols":[s for s,_ in values],"max_exposure_usdt":250},"ema_cross":ema}
