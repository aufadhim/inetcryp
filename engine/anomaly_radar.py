"""Independent anomaly hypotheses. Public data only; never submits orders."""
import math
import time
from datetime import datetime,timezone,timedelta
from engine.research_data import fetch_json,finite
from engine.observed_paper import check_quote

VERSION="anomaly_v1"
# Explicit identity map, not a ticker-name match. Listing status still checked.
IDENTITIES={"sleepless-ai":"AIUSDT","irys":"IRYSUSDT","iostoken":"IOSTUSDT",
            "pha":"PHAUSDT","particle-network":"PARTIUSDT","dymension":"DYMUSDT"}
HORIZONS={"30m":1800,"2h":7200,"24h":86400}
STABLE_IDS={"tether","usd-coin","dai","ethena-usde","first-digital-usd","true-usd","paypal-usd","usual-usd","usdd","frax","usd1-wlfi"}


def classify(coin,now,book=None):
    cap,volume,price,change=[finite(coin.get(k)) for k in ("market_cap","total_volume","current_price","price_change_percentage_1h_in_currency")]
    result={"coin_id":coin.get("id"),"symbol":coin.get("symbol"),"signal":"WATCH","score":0,
            "rule_version":VERSION,"source":"CoinGecko","source_updated_at":coin.get("last_updated"),
            "market_cap":cap,"volume_24h":volume,"price":price,"change_1h_pct":change,
            "binance_symbol":IDENTITIES.get(coin.get("id")),"paper_admission":False,"live_trading":False}
    if coin.get("id") in STABLE_IDS:return {**result,"reason":"stablecoin_excluded"}
    try:
        age=(now-datetime.fromisoformat(str(coin["last_updated"]).replace("Z","+00:00"))).total_seconds()
        if not 0<=age<=900:raise ValueError("Stale source")
        if any(v is None for v in (cap,volume,price,change)) or cap<=0 or volume<0 or price<=0:raise ValueError("Invalid data")
    except (ValueError,KeyError,TypeError):
        return {**result,"reason":"missing_invalid_or_stale_data"}
    ratio=volume/cap;result["volume_mc_ratio"]=ratio
    if change<=-5:return {**result,"reason":"falling_knife_excluded"}
    if change>=0 and ratio>1:
        return {**result,"signal":"SHORT","score":70,"reason":"high_turnover_on_rising_price_hypothesis_not_manipulation_proof"}
    if -5<change<=-2 and ratio>.15:
        if not result["binance_symbol"]:return {**result,"reason":"no_verified_exchange_identity_mapping"}
        if not book or check_quote(book,now):return {**result,"reason":"dip_requires_fresh_verified_orderbook"}
        bid,ask=float(book["bids"][0][0]),float(book["asks"][0][0]);mid=(bid+ask)/2
        bids=sum(float(p)*float(q) for p,q in book["bids"] if float(p)>=mid*.995)
        asks=sum(float(p)*float(q) for p,q in book["asks"] if float(p)<=mid*1.005)
        result["orderbook"]={"bid_notional":bids,"ask_notional":asks,"received_at":book["received_at"],"latency_ms":book["latency_ms"],"depth_limit":20,"band_pct":.5}
        if min(bids,asks)<25000:return {**result,"reason":"insufficient_observed_depth"}
        if abs(mid/price-1)>.01:return {**result,"reason":"cross_source_price_disagreement"}
        pressure=bids/asks;result["orderbook"]["bid_ask_ratio"]=pressure
        if pressure>=1.2:return {**result,"signal":"LONG","score":80 if ratio>.5 else 60,"reason":"dip_with_observed_bid_imbalance_hypothesis"}
        return {**result,"reason":"insufficient_bid_confirmation"}
    return {**result,"reason":"no_qualifying_anomaly"}


def observe_calls(reg,items,coins,now):
    by_id={c["id"]:c for c in coins if c.get("id")}
    for item in items:
        key=VERSION+":"+item["coin_id"]+":"+item["signal"]+":"+now.date().isoformat()
        if not reg.get("anomaly_call",key):
            reg.put("anomaly_call",key,{"id":key,"detected_at":now.isoformat(),"entry":item,"outcomes":{},"state":"LIVE"})
    calls=[]
    for key,payload in reg.db.execute("SELECT id,payload FROM records WHERE kind='anomaly_call'").fetchall():
        import json
        call=json.loads(payload);entry=call["entry"];detected=datetime.fromisoformat(call["detected_at"])
        for h,seconds in HORIZONS.items():
            if h in call["outcomes"]:continue
            due=detected+timedelta(seconds=seconds)
            if now<due:continue
            if now>due+timedelta(minutes=20):
                call["outcomes"][h]={"status":"MISSED","reason":"no_timely_price_no_reconstruction"};continue
            c=by_id.get(entry["coin_id"],{});price=finite(c.get("current_price"))
            try:updated=datetime.fromisoformat(c["last_updated"].replace("Z","+00:00"))
            except (KeyError,ValueError,TypeError):continue
            if price is None or price<=0 or not due<=updated<=now or (now-updated).total_seconds()>900:continue
            gross=(price/entry["price"]-1)*100
            directional=gross if entry["signal"]=="LONG" else -gross
            call["outcomes"][h]={"status":"OBSERVED","observed_at":now.isoformat(),"source_updated_at":updated.isoformat(),
                "price":price,"price_change_pct":gross,"directional_change_pct":directional,
                "estimated_long_net_pct":gross-.35 if entry["signal"]=="LONG" else None,
                "cost_policy":"Long: assumed 0.35pp costs; short: borrow/funding/execution unknown; NOT realized PnL"}
        call["state"]="CLOSED" if len(call["outcomes"])==3 else "LIVE"
        reg.put("anomaly_call",key,call);calls.append(call)
    return calls


def review(calls):
    report={}
    for h in HORIZONS:
        report[h]={}
        for direction in ("LONG","SHORT"):
            group=[c for c in calls if c["entry"]["signal"]==direction]
            outcomes=[c["outcomes"][h] for c in group if c["outcomes"].get(h,{}).get("status")=="OBSERVED"]
            report[h][direction]={"observed":len(outcomes),"missed":sum(c["outcomes"].get(h,{}).get("status")=="MISSED" for c in group),
                "mean_directional_change_pct":sum(o["directional_change_pct"] for o in outcomes)/len(outcomes) if outcomes else None,
                "positive_estimated_long_net":sum(o["estimated_long_net_pct"]>0 for o in outcomes) if direction=="LONG" else None,
                "sample_sufficient":len(outcomes)>=30,"interpretation":"Descriptive only; correlated samples, no portfolio or promotion"}
    return report


def collect(reg,public,now=None):
    now=now or datetime.now(timezone.utc)
    cache=reg.get("state","anomaly_market",{})
    attempt=reg.get("state","anomaly_fetch",{})
    last=attempt.get("attempted_at")
    error=attempt.get("error_type");http_status=attempt.get("http_status")
    if not last or (now-datetime.fromisoformat(last)).total_seconds()>=900:
        try:
            rows=fetch_json("https://api.coingecko.com/api/v3/coins/markets",{
                "vs_currency":"usd","order":"volume_desc","per_page":150,"page":1,"sparkline":"false","price_change_percentage":"1h"})
            if not isinstance(rows,list):raise ValueError("Expected markets array")
            # Keep only fields needed for reproducible screening.
            keys=("id","symbol","market_cap","total_volume","current_price","price_change_percentage_1h_in_currency","last_updated")
            cache={"received_at":datetime.now(timezone.utc).isoformat(),"coins":[{k:r.get(k) for k in keys} for r in rows if r.get("id")]}
            reg.put("state","anomaly_market",cache)
            error=None;http_status=200
        except Exception as exc:
            error=type(exc).__name__;http_status=getattr(getattr(exc,"response",None),"status_code",None)
        reg.put("state","anomaly_fetch",{"attempted_at":now.isoformat(),"error_type":error,"http_status":http_status})
    coins=cache.get("coins",[]);items=[];watch=[];books=0;active=set()
    try:
        info=public("exchangeInfo")
        active={r["symbol"] for r in info.get("symbols",[]) if r.get("status")=="TRADING" and r.get("isSpotTradingAllowed") and r.get("quoteAsset")=="USDT"}
    except Exception:pass
    for c in coins:
        book=None;change=finite(c.get("price_change_percentage_1h_in_currency"));symbol=IDENTITIES.get(c.get("id"))
        if change is not None and -5<change<=-2 and symbol in active and books<6:
            try:
                books+=1;start=time.perf_counter();raw=public("depth",symbol=symbol,limit=20)
                book={"bids":raw["bids"],"asks":raw["asks"],"received_at":datetime.now(timezone.utc).isoformat(),"latency_ms":(time.perf_counter()-start)*1000}
            except Exception:book=None
        decision=classify(c,datetime.now(timezone.utc),book)
        decision["binance_spot_listing_verified"]=symbol in active if symbol else False
        if decision["signal"]!="WATCH":items.append(decision)
        else:watch.append(decision)
    now=datetime.now(timezone.utc)
    calls=observe_calls(reg,items,coins,now)
    return {"version":VERSION,"as_of":now.isoformat(),"status":"degraded" if error else "ok","source_error":error,"source_http_status":http_status,
        "coverage":"150 highest-volume CoinGecko markets; not all coins/chains","items":sorted(items,key=lambda r:-r["score"]),
        "watch":watch,"calls":sorted(calls,key=lambda r:r["detected_at"],reverse=True)[:50],
        "total_calls":len(calls),"closed_calls":sum(c["state"]=="CLOSED" for c in calls),"evaluation":review(calls),
        "policy":"Prospective hypotheses, not probability, manipulation proof or trade execution. SHORT never executes on spot.",
        "paper_admission":False,"live_trading":False}
