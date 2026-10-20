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
    profiles = r.json()
    output = []
    for profile_index,profile in enumerate(profiles[:5]):
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


def research(reg, symbols):
    # Freeze one experiment per weekly epoch. The same holdout is never used
    # to tune another search; future versions need a newer holdout period.
    now=pd.Timestamp.now(tz="UTC")
    end = now.floor("D")
    end += pd.Timedelta(days=7-end.dayofweek)
    key = VERSION+":"+end.isoformat()
    active=reg.get("state","active_experiment")
    active_plan=reg.get("experiment",active) if active else None
    if active_plan and active_plan.get("status") not in {"completed","insufficient_data","rejected_validation"}:
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
        result = cached or simulate(frames,c,start,split_a)
        reg.put("development",key+":"+c.id,result)
        development.append({"candidate":asdict_candidate(c),"result":result})
        atomic(ROOT/"progress.json", {"phase":"development","completed":len(development),"total":12,"experiment":key})
    selected = max(development,key=lambda r:r["result"]["net_pnl"])
    c = Candidate(**selected["candidate"]["parameters"])
    validation = simulate(frames,c,split_a,split_b)
    stress = simulate(frames,c,split_a,split_b,cost=2)
    latency = simulate(frames,c,split_a,split_b,cost=2,delay_bars=1)
    folds = [simulate(frames,c,split_a+pd.Timedelta(days=12*i),split_a+pd.Timedelta(days=12*(i+1))) for i in range(3)]
    if now<end:
        failed=[]
        for name,result in (("validation",validation),("double_cost",stress),("latency_stress",latency)):
            if (result["net_pnl"]<=0 or result["expectancy"]<=0 or result["profit_factor"]<1.3
                    or result["trades"]<30 or result["max_drawdown_pct"]>5):
                failed.append(name+": failed before prospective holdout")
        plan.update(status="awaiting_fresh_holdout",development=development,selected=asdict_candidate(c),validation=validation,
                    double_cost=stress,latency_stress=latency,walk_forward=folds,
                    gate={"eligible":False,"reasons":["Development and validation complete; prospective holdout still collecting"]})
        if failed:
            plan.update(status="rejected_validation",gate={"eligible":False,"reasons":failed})
            reg.event("research_decision",{"experiment":key,"decision":"rejected_validation","reasons":failed})
        reg.put("experiment",key,plan)
        atomic(ROOT/"research-latest.json",plan)
        return
    # Only the development winner can consume final holdout.
    holdout = simulate(frames,c,holdout_start,end)
    cross = [simulate({s:f},c,holdout_start,end) for s,f in frames.items()]
    gate = research_gate(validation,stress,holdout,folds,cross)
    if latency["net_pnl"]<=0 or latency["expectancy"]<=0:
        gate["reasons"].append("latency_stress: negative edge after one-bar delay")
        gate["eligible"]=False
    plan.update(status="completed",development=development,selected=asdict_candidate(c),validation=validation,
                double_cost=stress,latency_stress=latency,holdout=holdout,walk_forward=folds,cross_coin=cross,gate=gate)
    reg.put("experiment",key,plan)
    reg.event("research_decision", {"experiment":key,"candidate":c.id,**gate})
    atomic(ROOT/"research-latest.json",plan)
    if gate["eligible"]:
        tournament = reg.get("state","tournament",{})
        for old_id,old in list(tournament.items()):
            if old["status"].startswith("paused") and not old["account"]["positions"]:
                reg.put("retired_account",old_id,old)
                del tournament[old_id]
        if c.id not in tournament and len(tournament)<3:
            tournament[c.id] = {"candidate":asdict_candidate(c),"experiment":key,"account":account(),"status":"challenger"}
            reg.put("state","tournament",tournament)
            reg.event("promoted_to_challenger", {"candidate":c.id,"scope":"isolated_paper_only"})


def asdict_candidate(c):
    from dataclasses import asdict
    return {"id":c.id,"parameters":asdict(c)}


def tournament_cycle(reg,symbols):
    tournament = reg.get("state","tournament",{})
    champion = reg.get("state","champion")
    rows = []
    prepared = {}
    required = set(symbols)
    for entry in tournament.values():
        required.update(entry["account"]["positions"])
    for symbol in sorted(required) if tournament else []:
        raw = public("klines",symbol=symbol,interval="15m",limit=300)
        frame = pd.DataFrame({"Open":[float(x[1]) for x in raw[:-1]],"High":[float(x[2]) for x in raw[:-1]],
            "Low":[float(x[3]) for x in raw[:-1]],"Close":[float(x[4]) for x in raw[:-1]],"Volume":[float(x[5]) for x in raw[:-1]]},
            index=pd.to_datetime([x[0] for x in raw[:-1]],unit="ms",utc=True))
        prepared[symbol] = features(frame)
    for cid, entry in tournament.items():
        c = Candidate(**entry["candidate"]["parameters"]).validate()
        if c.id!=cid:
            entry["status"]="paused_execution_model_changed"
        state = entry["account"]
        pending = {}
        for symbol, f in prepared.items():
            mask = signals(f,c)
            last = state["seen"].get(symbol)
            # On first enrollment, only observe the most recent completed bar.
            if not last:
                state["seen"][symbol] = f.index[-1].isoformat()
                continue
            indices = [i for i in range(100,len(f)) if f.index[i] > pd.Timestamp(last)]
            if last and pd.Timestamp(last) < f.index[99]:
                entry["status"] = "paused_data_gap"
                reg.event("paper_gap", {"candidate":cid,"symbol":symbol})
                continue
            for i in indices:
                bars,entries = pending.setdefault(f.index[i],({},{}))
                bars[symbol],entries[symbol] = f.iloc[i],bool(mask[i-1])
                bars[symbol]=bars[symbol].to_dict()
                bars[symbol]["decision_quote_volume"]=float(f.iloc[i-1].Close*f.iloc[i-1].Volume)
        for stamp,(bars,entries) in sorted(pending.items()):
            advance(state,c,bars,entries,stamp,allow_entry=entry["status"] in {"challenger","champion"})
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
            "validation":research_result.get("validation"),"holdout":research_result.get("holdout")}))
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


def main(once=False):
    ROOT.mkdir(parents=True,exist_ok=True)
    # A second worker must not run concurrent experiments/accounts.
    import msvcrt
    lock = open(ROOT/"worker.lock","a+b")
    lock.seek(0)
    try:
        msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    except OSError:
        return
    reg = Registry()
    symbols = []
    while True:
        try:
            atomic(ROOT/"status.json",{"status":"running","phase":"research","at":datetime.now(timezone.utc).isoformat()})
            symbols = universe(reg)
            from engine.research_data import collect_sources
            sources=collect_sources(reg,symbols)
            research(reg,symbols)
            tournament = tournament_cycle(reg,symbols)
            try:
                archive_orderbooks(reg,symbols)
            except Exception as exc:
                reg.event("orderbook_unavailable",{"error_type":type(exc).__name__})
            try:
                discovery(reg)
            except Exception as exc:
                reg.event("discovery_unavailable",{"error_type":type(exc).__name__})
            advice = adviser(reg)
            atomic(ROOT/"status.json",{"status":"sleeping","at":datetime.now(timezone.utc).isoformat(),
                "version":VERSION,"symbols":symbols,"tournament":tournament,"adviser":advice,
                "sources":sources,
                "research":json.loads((ROOT/"research-latest.json").read_text(encoding="utf-8")) if (ROOT/"research-latest.json").exists() else {"status":"pending_or_insufficient_data"}})
        except Exception as exc:
            atomic(ROOT/"status.json",{"status":"error","at":datetime.now(timezone.utc).isoformat(),"error_type":type(exc).__name__})
        if once:
            break
        time.sleep(300)


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--once",action="store_true")
    main(parser.parse_args().once)
