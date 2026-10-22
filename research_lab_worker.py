"""Research every UTC day; paper tournament every five minutes. Public data only."""
import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import requests
from engine.historical_data import historical
from engine.research_lab import (VERSION, Candidate, Registry, account, advance, candidates,
                                 features, forward_gate, research_gate, signals, simulate, stats,
                                 compare_forward, holdout_watermark)

ROOT = Path("data/lab")


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.name=="progress.json":data={**data,"at":datetime.now(timezone.utc).isoformat()}
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent=2, allow_nan=False), encoding="utf-8")
    temp.replace(path)


def public(path, **params):
    r = requests.get("https://data-api.binance.vision/api/v3/"+path, params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def universe(reg):
    from engine.dynamic_universe import shortlist
    info,tickers=public("exchangeInfo"),public("ticker/24hr")
    rows = shortlist(info,tickers,time.time()*1000)
    from engine.dynamic_universe import STABLES
    eligible={r["symbol"] for r in info.get("symbols",[]) if r.get("status")=="TRADING" and r.get("quoteAsset")=="USDT"
              and r.get("isSpotTradingAllowed") and r.get("baseAsset") not in STABLES
              and not r.get("baseAsset","").endswith(("UP","DOWN","BULL","BEAR"))}
    liquid=sorted([r for r in tickers if r.get("symbol") in eligible and float(r.get("quoteVolume",0))>=5_000_000
                   and float(r.get("count",0))>=5000],key=lambda r:-float(r["quoteVolume"]))
    symbols = list(dict.fromkeys(["BTCUSDT", "ETHUSDT", "SOLUSDT"]+[r["symbol"] for r in rows[:2]]+[r["symbol"] for r in liquid]))[:8]
    today=datetime.now(timezone.utc).date().isoformat()
    catalog=reg.get("state","exchange_catalog",{})
    if catalog.get("date")!=today:
        now=datetime.now(timezone.utc).isoformat()
        snapshot={"date":today,"observed_at":now,"symbols":[{k:r.get(k) for k in ("symbol","status","baseAsset","quoteAsset")} for r in info.get("symbols",[])]}
        reg.event("exchange_catalog_observed",snapshot)
        reg.put("state","exchange_catalog",snapshot)
    reg.event("universe_observed", {"symbols": symbols, "selection_bias": "current listing/momentum; historical survivors only"})
    return symbols


def discovery(reg):
    """Archive DEX observations for future causal tests; never fake historical signals."""
    r = requests.get("https://api.dexscreener.com/token-profiles/latest/v1", timeout=15)
    r.raise_for_status()
    profiles = r.json()[:5]
    # Follow old discoveries through their deadlines, not just today's latest profiles.
    due_tokens=[];seen_tokens={(p.get("chainId"),p.get("tokenAddress")) for p in profiles}
    now=datetime.now(timezone.utc)
    for payload, in reg.db.execute("SELECT payload FROM records WHERE kind='radar_call'"):
        call=json.loads(payload)
        if call.get("market")!="dex":continue
        age=(now-datetime.fromisoformat(call["detected_at"])).total_seconds()
        if not any(h not in call["outcomes"] and seconds-300<=age<=seconds+600 for h,seconds in (("30m",1800),("2h",7200),("24h",86400))):continue
        m=call["metadata"];identity=(m["chain"],m["token_address"])
        if identity in seen_tokens:continue
        seen_tokens.add(identity);due_tokens.append({"chainId":identity[0],"tokenAddress":identity[1]})
        if len(due_tokens)>=4:break
    profiles+=due_tokens
    output = []
    for profile_index,profile in enumerate(profiles):
        chain, address = profile.get("chainId"), profile.get("tokenAddress")
        if not chain or not address:
            continue
        security=reg.get("token_security",chain+":"+address)
        if profile_index<2 and (not security or (datetime.now(timezone.utc)-datetime.fromisoformat(security["observed_at"])).total_seconds()>21600):
            from engine.research_data import token_security
            security=token_security(chain,address)
            security["observed_at"]=datetime.now(timezone.utc).isoformat()
            reg.put("token_security",chain+":"+address,security)
            reg.event("token_security_observation",security)
        response = requests.get(f"https://api.dexscreener.com/token-pairs/v1/{chain}/{address}", timeout=15)
        response.raise_for_status()
        for pair in response.json()[:3]:
            from engine.research_data import dex_risk
            output.append({"chain": chain, "token_address": address, "pair": pair.get("pairAddress"),
                "liquidity": (pair.get("liquidity") or {}).get("usd"), "volume": pair.get("volume"),
                "change": pair.get("priceChange"), "price_usd": pair.get("priceUsd"),
                "risk":dex_risk(pair),"security":security or {"status":"not_checked"},
                "policy": "observe_only_unverified_sellability_and_holders"})
    reg.event("dex_observation", {"at": datetime.now(timezone.utc).isoformat(), "pairs": output})
    atomic(ROOT/"discovery.json", {"as_of": datetime.now(timezone.utc).isoformat(), "pairs": output,
        "fundamentals": "CoinGecko metadata archived separately; unlock and holder history unavailable",
        "fluxscout": "unverified_api", "dawn_trade": "unverified_data_api"})


def archive_orderbooks(reg, symbols):
    from engine.multi_exchange import CrossExchangeMarket
    market = CrossExchangeMarket()
    for symbol in symbols[:3]:
        snapshot=market.snapshot(symbol)
        reg.event("cross_exchange_observation", {"observed_at":datetime.now(timezone.utc).isoformat(),
            "snapshot":snapshot,"historical_use":"forward_archive_only"})


def research_exits(reg,plan):
    if plan.get("status")!="completed":return
    key=plan["id"]+":paired_exits_v1"
    if reg.get("exit_research",key):return
    from engine.exit_research import paired_exits
    report={"id":key,"status":"running","results":[],"paper_admission":False,
            "selection":"First two frozen daily candidates, not selected by exit results"}
    atomic(ROOT/"exit-research.json",report)
    start,end=pd.Timestamp(plan["data_start"]),pd.Timestamp(plan["data_end"])
    frames={}
    for symbol in plan["universe"]:
        try:
            frame,_=historical(symbol,start,end,cache_dir="data/lab/cache")
            frames[symbol]=features(frame)
        except Exception as exc:reg.event("exit_dataset_failed",{"symbol":symbol,"error_type":type(exc).__name__})
    report["dataset_symbols"]=sorted(frames)
    if len(frames)<3:
        report.update(status="insufficient_data")
    else:
        for parameters in plan["parameters"][:2]:
            c=Candidate(**parameters).validate()
            normal=paired_exits(frames,c,start,end)
            stress=paired_exits(frames,c,start,end,cost=2,delay_bars=1)
            report["results"].append({"candidate":asdict_candidate(c),"normal":normal,"stress":stress})
            atomic(ROOT/"exit-research.json",report)
        report.update(status="completed",completed_at=pd.Timestamp.now(tz="UTC").isoformat())
    reg.put("exit_research",key,report)
    atomic(ROOT/"exit-research.json",report)


def evaluate_daily(reg, plan):
    """Cost attribution and chronological stability; never converts exploration to admission."""
    if plan.get("status")!="completed":return
    key=plan["id"]+":cost_review_v3"
    existing=reg.get("daily_review",key)
    if existing:return existing
    report={"id":key,"status":"running","source":plan["id"],"candidates":[],
            "policy":"reused_development_diagnostic_not_independent_validation","paper_admission":False}
    atomic(ROOT/"daily-review.json",report)
    start,end=pd.Timestamp(plan["data_start"]),pd.Timestamp(plan["data_end"])
    frames={}
    for symbol in plan["universe"]:
        try:
            frame,_=historical(symbol,start,end,cache_dir="data/lab/cache")
            frames[symbol]=features(frame)
        except Exception as exc:reg.event("daily_review_dataset_failed",{"symbol":symbol,"error_type":type(exc).__name__})
    if len(frames)<3:return
    report["dataset_symbols"]=sorted(frames)
    for row in plan["results"]:
        c=Candidate(**row["candidate"]["parameters"])
        # Same signal timing isolates cost effects; delayed execution is separate.
        normal=simulate(frames,c,start,end,include_diagnostics=True,cost_guard=plan.get("cost_guard",False))
        doubled=simulate(frames,c,start,end,cost=2,include_diagnostics=False,cost_guard=plan.get("cost_guard",False))
        delayed=simulate(frames,c,start,end,cost=2,delay_bars=1,include_diagnostics=False,cost_guard=plan.get("cost_guard",False))
        folds=[simulate(frames,c,start+(end-start)*i/3,start+(end-start)*(i+1)/3,
                        include_diagnostics=False,cost_guard=plan.get("cost_guard",False)) for i in range(3)]
        reasons=[]
        if normal["net_pnl"]<=0:reasons.append("negative_after_normal_costs")
        if doubled["net_pnl"]<=0:reasons.append("negative_after_double_costs")
        if delayed["net_pnl"]<=0:reasons.append("negative_after_cost_and_latency")
        if sum(f["net_pnl"]>0 for f in folds)<2:reasons.append("unstable_across_three_periods")
        if normal["trades"]<30:reasons.append("insufficient_trade_sample")
        if normal["profit_factor"]<1.3:reasons.append("profit_factor_below_1_3")
        if max(normal["max_drawdown_pct"],doubled["max_drawdown_pct"],delayed["max_drawdown_pct"])>5:
            reasons.append("drawdown_above_5_percent")
        report["candidates"].append({"candidate":row["candidate"],"normal":normal,
            "double_cost_same_timing":doubled,"cost_and_latency":delayed,
            "folds":folds,"rejection_reasons":reasons,"worth_fresh_validation":not reasons})
        atomic(ROOT/"daily-review.json",report)
    report.update(status="completed",completed_at=pd.Timestamp.now(tz="UTC").isoformat(),
                  worth_fresh_validation=sum(r["worth_fresh_validation"] for r in report["candidates"]))
    reg.put("daily_review",key,report)
    reg.event("daily_cost_review",{"id":key,"reviewed":len(report["candidates"]),
                                   "worth_fresh_validation":report["worth_fresh_validation"]})
    atomic(ROOT/"daily-review.json",report)
    return report


def daily_research(reg, symbols, now=None):
    """Bounded exploratory queue; never read the final holdout or admit paper accounts."""
    now=pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="UTC")
    day=now.tz_convert("Asia/Jakarta").date().isoformat()
    key=VERSION+":daily:"+day
    previous=reg.get("daily_research",key)
    if previous and previous.get("status") in {"completed","insufficient_data"}:
        return previous
    active=reg.get("state","active_experiment")
    frozen=reg.get("experiment",active) if active else None
    if not frozen:return {"status":"waiting_for_frozen_experiment"}
    # All exploratory candles precede the frozen experiment's validation boundary.
    # Repeated exploration is development, not fresh independent validation.
    cutoff=pd.Timestamp(frozen["start"])+pd.Timedelta(days=144)
    cutoff=min(cutoff,now.floor("15min"),pd.Timestamp(frozen["holdout_start"]))
    start=cutoff-pd.Timedelta(days=90)
    if previous:
        pool=[Candidate(**p).validate() for p in previous["parameters"]]
        symbols=previous["universe"]
    else:
        pool=[]
        for proposal in reg.get("state","proposals",[])[:2]:
            try:pool.append(Candidate(**proposal).validate())
            except (ValueError,TypeError):continue
        # Deterministic daily rotations keep the search bounded and reproducible.
        offset=pd.Timestamp(day).dayofyear
        families=["ema_pullback","channel_breakout","rsi_reversion","vwap_reclaim","flow_breakout","compression"]
        for i in range(8):
            pool.append(Candidate(families[(offset+i)%6],stop_pct=[1.0,1.5,2.0][(offset+i)%3],
                target_pct=[3.0,4.5,6.0][(offset//3+i)%3],hold_bars=[8,16,24][(offset//7+i)%3],volume_ratio=[1.2,1.5,1.8][i%3]).validate())
        pool=list({c.id:c for c in pool}.values())[:6]
    plan=previous or {"id":key,"status":"running","frozen_at":now.isoformat(),"universe":symbols[:8],
        "parameters":[asdict_candidate(c)["parameters"] for c in pool],"results":[],
        "data_start":start.isoformat(),"data_end":cutoff.isoformat(),"max_trials":6,"cost_guard":True,
        "policy":"exploratory_development_only_no_holdout_no_paper_admission"}
    start,cutoff=pd.Timestamp(plan["data_start"]),pd.Timestamp(plan["data_end"])
    reg.put("daily_research",key,plan)
    atomic(ROOT/"daily-research.json",plan)
    frames={}
    for symbol in plan["universe"]:
        try:
            frame,_=historical(symbol,start,cutoff,cache_dir="data/lab/cache")
            frames[symbol]=features(frame)
        except Exception as exc:reg.event("daily_dataset_failed",{"symbol":symbol,"error_type":type(exc).__name__})
    if len(frames)<3:
        plan.update(status="insufficient_data",completed_at=now.isoformat())
    else:
        done={r["candidate"]["id"] for r in plan["results"]}
        for c in pool:
            if c.id in done:continue
            normal=simulate(frames,c,start,cutoff,include_diagnostics=False,cost_guard=plan.get("cost_guard",False))
            stress=simulate(frames,c,start,cutoff,cost=2,delay_bars=1,include_diagnostics=False,cost_guard=plan.get("cost_guard",False))
            plan["results"].append({"candidate":asdict_candidate(c),"development":normal,"cost_latency_stress":stress})
            reg.put("daily_research",key,plan)
            atomic(ROOT/"daily-research.json",plan)
        ranked=sorted(plan["results"],key=lambda r:r["cost_latency_stress"]["net_pnl"],reverse=True)
        promising=[r for r in ranked if r["cost_latency_stress"]["net_pnl"]>0
            and r["cost_latency_stress"]["profit_factor"]>=1.3 and r["cost_latency_stress"]["trades"]>=30
            and r["cost_latency_stress"]["max_drawdown_pct"]<=5]
        plan.update(status="completed",completed_at=pd.Timestamp.now(tz="UTC").isoformat(),
                    promising=len(promising),best=ranked[0] if ranked else None)
        if promising:
            reg.put("state","proposals",[r["candidate"]["parameters"] for r in promising[:2]])
        # Queue for the NEXT frozen weekly experiment only; never change its winner.
        reg.event("daily_research_completed",{"id":key,"trials":len(ranked),"promising":len(promising),"paper_admission":False})
    reg.put("daily_research",key,plan)
    atomic(ROOT/"daily-research.json",plan)
    return plan


def research(reg, symbols):
    # Freeze one experiment per weekly epoch. The same holdout is never used
    # to tune another search; future versions need a newer holdout period.
    now=pd.Timestamp.now(tz="UTC")
    end = now.floor("D")
    end += pd.Timedelta(days=7-end.dayofweek)
    key = VERSION+":"+end.isoformat()
    active=reg.get("state","active_experiment")
    active_plan=reg.get("experiment",active) if active else None
    if active_plan and active.startswith(VERSION+":") and active_plan.get("status") not in {"completed","insufficient_data","rejected_validation"}:
        key=active
        end=pd.Timestamp(active_plan["end"])
    previous = reg.get("experiment",key)
    if previous and previous.get("status") in {"completed","insufficient_data","rejected_validation"}:
        return
    if previous and previous.get("development") and now<end:
        failed=[]
        for name in ("validation","double_cost","latency_stress"):
            result=previous.get(name,{})
            if (result.get("net_pnl",0)<=0 or result.get("expectancy",0)<=0
                    or result.get("profit_factor",0)<1.3 or result.get("trades",0)<30
                    or result.get("max_drawdown_pct",100)>5):
                failed.append(name+": failed before prospective holdout")
        if failed:
            previous.update(status="rejected_validation",gate={"eligible":False,"reasons":failed})
            reg.put("experiment",key,previous)
            reg.event("research_decision",{"experiment":key,"decision":"rejected_validation","reasons":failed})
            atomic(ROOT/"research-latest.json",previous)
        return
    start = end-pd.Timedelta(days=180)
    split_a, split_b = start+pd.Timedelta(days=108), start+pd.Timedelta(days=144)
    used=holdout_watermark(reg)
    holdout_start=max(split_b,used if used is not None else split_b,now.ceil("D")) if not previous else pd.Timestamp(previous["holdout_start"])
    if previous:
        symbols = previous["universe"]
    pool = candidates()
    proposals = reg.get("state","proposals",[])[:2]
    if proposals:
        pool = pool[:10] + [Candidate(**p).validate() for p in proposals]
    if previous:
        pool = [Candidate(**item["parameters"]).validate() for item in previous["candidates"]]
    plan = {"id":key,"start":str(start),"end":str(end),"candidates":[asdict_candidate(c) for c in pool],
        "max_trials":12,"selection":"development_only","status":"running","datasets":{},
        "universe":symbols,"warning":"Current universe survivorship bias; historical scores alone cannot promote champion"}
    plan.update(holdout_start=holdout_start.isoformat(),frozen_at=(previous or {}).get("frozen_at",now.isoformat()),
        execution_model="spread_5bps_plus_slippage_5bps_plus_volume_impact",holdout_policy="nonoverlap_after_candidate_freeze")
    # Preserve frozen legacy execution. New experiments share paper's cost guard.
    plan["cost_guard"]=previous.get("cost_guard",False) if previous else True
    from functools import partial
    run_sim=partial(simulate,cost_guard=plan["cost_guard"])
    if now<end:
        plan.update(status="awaiting_fresh_holdout",gate={"eligible":False,"reasons":["Frozen candidates wait for new, nonoverlapping holdout candles"]})
        reg.put("experiment",key,plan)
        reg.put("state","active_experiment",key)
        atomic(ROOT/"research-latest.json",plan)
    reg.put("experiment",key,plan)
    frames = {}
    atomic(ROOT/"progress.json",{"phase":"datasets","completed":0,"total":len(symbols),"experiment":key})
    for symbol in symbols:
        try:
            fetch_end=end if now>=end else pd.Timestamp(plan["frozen_at"]).floor("15min")
            frame, provenance = historical(symbol,start,fetch_end,cache_dir="data/lab/cache")
            frames[symbol] = features(frame)
            plan["datasets"][symbol] = provenance
        except Exception as exc:
            reg.event("dataset_failed", {"symbol":symbol,"error_type":type(exc).__name__})
        atomic(ROOT/"progress.json",{"phase":"datasets","completed":len(frames),"total":len(symbols),"experiment":key})
    if len(frames) < 3:
        plan.update(status="insufficient_data")
        reg.put("experiment",key,plan)
        return
    development = []
    for c in pool:
        cached = reg.get("development",key+":"+c.id)
        result = cached or run_sim(frames,c,start,split_a)
        reg.put("development",key+":"+c.id,result)
        development.append({"candidate":asdict_candidate(c),"result":result})
        atomic(ROOT/"progress.json", {"phase":"development","completed":len(development),"total":12,"experiment":key})
    selected = max(development,key=lambda r:r["result"]["net_pnl"])
    c = Candidate(**selected["candidate"]["parameters"])
    validation = run_sim(frames,c,split_a,split_b)
    stress = run_sim(frames,c,split_a,split_b,cost=2)
    latency = run_sim(frames,c,split_a,split_b,cost=2,delay_bars=1)
    from engine.research_analysis import baselines,benchmark_gate
    benchmarks=baselines(frames,split_a,split_b,cost_guard=plan["cost_guard"])
    baseline_decision=benchmark_gate(validation,benchmarks)
    atomic(ROOT/"loss-diagnosis.json",{"experiment":key,"candidate":c.id,"validation":validation.get("diagnostics"),
        "baselines":benchmarks,"baseline_gate":baseline_decision})
    folds = [run_sim(frames,c,split_a+pd.Timedelta(days=12*i),split_a+pd.Timedelta(days=12*(i+1))) for i in range(3)]
    if now<end:
        failed=[]
        failed.extend(baseline_decision["reasons"])
        for name,result in (("validation",validation),("double_cost",stress),("latency_stress",latency)):
            if (result["net_pnl"]<=0 or result["expectancy"]<=0 or result["profit_factor"]<1.3
                    or result["trades"]<30 or result["max_drawdown_pct"]>5):
                failed.append(name+": failed before prospective holdout")
        plan.update(status="awaiting_fresh_holdout",development=development,selected=asdict_candidate(c),validation=validation,
                    double_cost=stress,latency_stress=latency,walk_forward=folds,
                    baselines=benchmarks,baseline_gate=baseline_decision,
                    gate={"eligible":False,"reasons":["Development and validation complete; prospective holdout still collecting"]})
        if failed:
            plan.update(status="rejected_validation",gate={"eligible":False,"reasons":failed})
            reg.event("research_decision",{"experiment":key,"decision":"rejected_validation","reasons":failed})
        reg.put("experiment",key,plan)
        atomic(ROOT/"research-latest.json",plan)
        return
    # Only the development winner can consume final holdout.
    holdout = run_sim(frames,c,holdout_start,end)
    holdout_baselines=baselines(frames,holdout_start,end,cost_guard=plan["cost_guard"])
    holdout_baseline_gate=benchmark_gate(holdout,holdout_baselines)
    cross = [run_sim({s:f},c,holdout_start,end) for s,f in frames.items()]
    gate = research_gate(validation,stress,holdout,folds,cross)
    gate["reasons"].extend(baseline_decision["reasons"]+holdout_baseline_gate["reasons"])
    gate["eligible"]=not gate["reasons"]
    if latency["net_pnl"]<=0 or latency["expectancy"]<=0:
        gate["reasons"].append("latency_stress: negative edge after one-bar delay")
        gate["eligible"]=False
    plan.update(status="completed",development=development,selected=asdict_candidate(c),validation=validation,
                double_cost=stress,latency_stress=latency,holdout=holdout,walk_forward=folds,cross_coin=cross,gate=gate,
                baselines=benchmarks,baseline_gate=baseline_decision,holdout_baselines=holdout_baselines)
    reg.put("experiment",key,plan)
    reg.event("research_decision", {"experiment":key,"candidate":c.id,**gate})
    atomic(ROOT/"research-latest.json",plan)
    if gate["eligible"]:
        reg.put("admission",c.id,{"candidate":asdict_candidate(c),"experiment":key,"status":"queued"})
        reg.event("paper_admission_queued",{"candidate":c.id,"scope":"isolated_paper_only"})


def asdict_candidate(c):
    from dataclasses import asdict
    return {"id":c.id,"parameters":asdict(c)}


def tournament_cycle(reg,symbols):
    from engine.observed_paper import MODEL, observed_step
    tournament = reg.get("state","tournament",{})
    # The monitor is the sole writer of paper accounts. Research only queues admissions.
    for row in list(reg.db.execute("SELECT id,payload FROM records WHERE kind='admission'")):
        admission=json.loads(row[1])
        if admission["status"]!="queued":continue
        for old_id,old in list(tournament.items()):
            if old["status"].startswith("paused") and not old["account"]["positions"]:
                reg.put("retired_account",old_id,old);del tournament[old_id]
        if row[0] in tournament:
            admission["status"]="consumed";reg.put("admission",row[0],admission)
            continue
        if len(tournament)>=3:continue
        c=Candidate(**admission["candidate"]["parameters"]).validate()
        if c.id!=row[0]:continue
        tournament[c.id]={"candidate":admission["candidate"],"experiment":admission["experiment"],"account":account(),"status":"challenger"}
        reg.put("state","tournament",tournament)
        admission["status"]="consumed";reg.put("admission",row[0],admission)
        reg.event("promoted_to_challenger",{"candidate":c.id})
    champion = reg.get("state","champion")
    rows = []
    prepared = {}
    required = set(symbols)
    for entry in tournament.values():
        required.update(entry["account"]["positions"])
    books={}
    for symbol in sorted(required) if tournament else []:
        try:
            raw = public("klines",symbol=symbol,interval="15m",limit=300)
            frame = pd.DataFrame({"Open":[float(x[1]) for x in raw[:-1]],"High":[float(x[2]) for x in raw[:-1]],
                "Low":[float(x[3]) for x in raw[:-1]],"Close":[float(x[4]) for x in raw[:-1]],"Volume":[float(x[5]) for x in raw[:-1]]},
                index=pd.to_datetime([x[0] for x in raw[:-1]],unit="ms",utc=True))
            prepared[symbol] = features(frame)
            started=time.perf_counter()
            book=public("depth",symbol=symbol,limit=20)
            books[symbol]={"bids":book["bids"],"asks":book["asks"],
                "latency_ms":(time.perf_counter()-started)*1000,"received_at":datetime.now(timezone.utc).isoformat()}
        except (requests.RequestException,ValueError,KeyError,TypeError) as exc:
            reg.event("paper_market_unavailable",{"symbol":symbol,"error_type":type(exc).__name__})
    for cid, entry in tournament.items():
        c = Candidate(**entry["candidate"]["parameters"]).validate()
        if c.id!=cid:
            entry["status"]="paused_execution_model_changed"
        state = entry["account"]
        observations={}
        if state.get("execution_model")!=MODEL and (state["trades"] or state["positions"]):
            entry["status"]="paused_execution_model_changed"
        for symbol, f in prepared.items():
            if symbol not in books:continue
            mask = signals(f,c)
            if not state["first_at"]:
                state["seen"][symbol] = f.index[-1].isoformat()
            atr=float(f.iloc[-1].atr_pct)
            observations[symbol]={"book":books[symbol],"signal":bool(mask[-1]),"candle_at":f.index[-1].isoformat(),
                "regime":str(f.iloc[-1].regime),"volatility":"high" if atr>=1.5 else "medium" if atr>=.5 else "low"}
        if not entry["status"].startswith("paused_execution"):
            events=observed_step(state,c,observations,allow_entry=entry["status"] in {"challenger","champion"})
            for event in events:reg.event("observed_paper_execution",{"candidate":cid,**event})
        performance = forward_gate(state)
        if performance["max_drawdown_pct"] > 5:
            entry["status"] = "paused_drawdown"
            reg.event("candidate_paused",{"candidate":cid,"reason":"forward_drawdown"})
        rows.append({"id":cid,"family":c.family,"status":entry["status"],**performance})
    eligible = [r for r in rows if r["eligible"] and r["status"] in {"champion","challenger"}]
    if champion in tournament and tournament[champion]["status"].startswith("paused"):
        reg.event("paper_champion_paused",{"candidate":champion})
        champion=None
        reg.put("state","champion",None)
    if eligible:
        best=None
        if champion is None:
            best=max(eligible,key=lambda r:r["net_pnl"])
        else:
            replacements=[]
            for row in eligible:
                if row["id"]==champion:continue
                comparison=compare_forward(tournament[row["id"]]["account"],tournament[champion]["account"])
                reg.event("champion_comparison",{"candidate":row["id"],"incumbent":champion,**comparison})
                if comparison["replace"]:
                    replacements.append((comparison["mean_daily_excess_return"],row))
            if replacements:
                best=max(replacements,key=lambda item:item[0])[1]
        if best is not None and best["id"] != champion:
            if champion in tournament:
                tournament[champion]["status"]="challenger"
            champion = best["id"]
            tournament[champion]["status"]="champion"
            reg.put("state","champion",champion)
            reg.event("paper_champion_changed",{"candidate":champion,"live_trading":False})
    for row in rows:
        row["status"]=tournament[row["id"]]["status"]
    reg.put("state","tournament",tournament)
    return {"champion":champion,"accounts":rows,"live_trading":False,
            "paper_promotion":"30 days, 200 trades, PF >=1.3, positive expectancy, drawdown <=5%"}


def adviser(reg):
    # Explicit env only: this worker never loads dotenv or account credentials.
    if not (ROOT/"research-latest.json").exists():
        return {"status":"waiting_for_first_research_result"}
    today = datetime.now(timezone.utc).date().isoformat()
    research_result = json.loads((ROOT/"research-latest.json").read_text(encoding="utf-8"))
    if research_result.get("status") not in {None,"completed","rejected_validation"}:
        return {"status":"waiting_for_completed_frozen_experiment"}
    previous = reg.get("advice",today)
    if (previous and previous.get("experiment")==research_result.get("id")
            and (previous.get("status")=="bounded_proposals_for_next_epoch" or previous.get("attempts",0)>=2)):
        return previous
    if not os.getenv("GEMINI_API_KEY"):
        return {"status":"awaiting_main_worker_adviser"}
    from engine.gemini_config import generate
    prompt = ('Evaluasi eksperimen. Jawab JSON ringkas dengan analysis dan hypotheses (maksimal dua). '
        'Setiap hypothesis berisi family, stop_pct (0.5..3), target_pct (1..8), hold_bars (integer 4..48), '
        'volume_ratio (1..3). family harus salah satu families. Hindari kode dan janji profit. Konteks: '+
        json.dumps({"families":[c.family for c in candidates()[::2]],"gate":research_result.get("gate"),
            "validation":research_result.get("validation"),"holdout":research_result.get("holdout"),
            "baselines":research_result.get("baselines"),"diagnostic_interpretation":"Groups describe associations; avoid tuning to small samples"}))
    response = generate({"contents":[{"parts":[{"text":prompt}]}],
        "generationConfig":{"maxOutputTokens":8192,"responseMimeType":"application/json"}},
        os.environ["GEMINI_API_KEY"],operation="research_lab")
    text = ""
    if response.status_code==200:
        data=response.json().get("candidates",[])
        if data:
            text="\n".join(p.get("text","") for p in data[0].get("content",{}).get("parts",[]) if not p.get("thought"))
    result = {"status":"unavailable" if not text else "advisory_only","text":text[:5000],
              "experiment":research_result.get("id"),"attempts":(previous or {}).get("attempts",0)+1}
    if text:
        try:
            clean = text.strip()
            if clean.startswith("```"):
                clean = clean.split("\n",1)[1].rsplit("```",1)[0]
            hypotheses = json.loads(clean).get("hypotheses",[])
            from dataclasses import asdict
            proposals = []
            for item in hypotheses[:2]:
                c = Candidate(**item).validate()
                if not isinstance(c.hold_bars,int):
                    raise ValueError("hold_bars must be integer")
                proposals.append(asdict(c))
            reg.put("state","proposals",proposals)
            result["status"]="bounded_proposals_for_next_epoch"
            result["proposals"]=proposals
        except (ValueError,TypeError,KeyError):
            result["status"]="advisory_only_invalid_proposal"
    reg.put("advice",today,result)
    return result


def main(once=False,role="monitor"):
    ROOT.mkdir(parents=True,exist_ok=True)
    # A second worker must not run concurrent experiments/accounts.
    import msvcrt
    lock = open(ROOT/("worker-"+role+".lock"),"a+b")
    lock.seek(0)
    try:
        msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    except OSError:
        return
    reg = Registry()
    symbols = []
    while True:
        try:
            heartbeat=ROOT/(role+"_status.json")
            atomic(heartbeat,{"status":"running","role":role,"at":datetime.now(timezone.utc).isoformat()})
            symbols = universe(reg)
            if role=="research":
                research(reg,symbols)
                daily_research(reg,symbols)
                daily_path=ROOT/"daily-research.json"
                if daily_path.exists():
                    daily_plan=json.loads(daily_path.read_text(encoding="utf-8"))
                    evaluate_daily(reg,daily_plan)
                    research_exits(reg,daily_plan)
                legacy_path=Path("data/paper_trading_journal.json")
                if legacy_path.exists():
                    from engine.research_analysis import diagnose
                    legacy=json.loads(legacy_path.read_text(encoding="utf-8"))
                    atomic(ROOT/"legacy-loss-diagnosis.json",{"source":"legacy_journal","diagnostics":diagnose(legacy.get("history",[]))})
            elif role=="collector":
                from engine.research_data import collect_sources
                collect_sources(reg,symbols)
                archive_orderbooks(reg,symbols)
                try:
                    discovery(reg)
                except Exception as exc:
                    reg.event("dex_discovery_unavailable",{"error_type":type(exc).__name__})
                from engine.opportunity_radar import collect as collect_radar
                dex_snapshot={}
                dex_path=ROOT/"discovery.json"
                if dex_path.exists():
                    observed=json.loads(dex_path.read_text(encoding="utf-8"))
                    if 0<=(datetime.now(timezone.utc)-datetime.fromisoformat(observed["as_of"])).total_seconds()<=900:
                        dex_snapshot=observed
                atomic(ROOT/"opportunity-radar.json",collect_radar(reg,public,dex_snapshot.get("pairs",[])))
                try:
                    from engine.anomaly_radar import collect as collect_anomalies
                    atomic(ROOT/"anomaly-radar.json",collect_anomalies(reg,public))
                except Exception as exc:
                    reg.event("anomaly_radar_error",{"error_type":type(exc).__name__})
            else:
                tournament = tournament_cycle(reg,symbols)
                try:
                    from engine.anomaly_paper import cycle as anomaly_paper_cycle
                    atomic(ROOT/"anomaly-paper.json",anomaly_paper_cycle(reg,public))
                except Exception as exc:
                    reg.event("anomaly_paper_error",{"error_type":type(exc).__name__})
                try:
                    from engine.online_learning import cycle as online_cycle
                    atomic(ROOT/"online-learning.json",online_cycle(public,ROOT))
                    atomic(ROOT/"online-radar-learning.json",online_cycle(public,ROOT,radar=True))
                except Exception as exc:
                    reg.event("online_learning_error",{"error_type":type(exc).__name__})
                atomic(ROOT/"status.json",{"status":"sleeping","at":datetime.now(timezone.utc).isoformat(),
                    "version":VERSION,"symbols":symbols,"tournament":tournament,
                    "sources":reg.get("state","source_health",{}),"adviser":reg.get("advice",datetime.now(timezone.utc).date().isoformat(),{}),
                    "research":json.loads((ROOT/"research-latest.json").read_text(encoding="utf-8")) if (ROOT/"research-latest.json").exists() else {"status":"pending"}})
            atomic(heartbeat,{"status":"sleeping","role":role,"at":datetime.now(timezone.utc).isoformat(),"symbols":symbols})
        except Exception as exc:
            atomic(ROOT/(role+"_status.json"),{"status":"error","role":role,"at":datetime.now(timezone.utc).isoformat(),"error_type":type(exc).__name__})
        if once:
            break
        time.sleep(30 if role=="monitor" else 300)
    reg.db.close()
    lock.close()


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--once",action="store_true")
    parser.add_argument("--role",choices=["monitor","research","collector"],default="monitor")
    args=parser.parse_args()
    main(args.once,args.role)
