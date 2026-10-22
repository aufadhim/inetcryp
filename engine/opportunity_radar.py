"""Public-data discovery and prospective outcome journal, not buy instructions."""
import json
import math
from datetime import datetime,timezone
from engine.dynamic_universe import shortlist

HORIZONS={"30m":1800,"2h":7200,"24h":86400}


def record(reg,market,identity,price,now,metadata):
    try:price=float(price)
    except (ValueError,TypeError):return False
    if not math.isfinite(price) or price<=0:return False
    key=market+":"+identity+":"+now.date().isoformat()
    if reg.get("radar_call",key):return False
    reg.put("radar_call",key,{"id":key,"market":market,"identity":identity,"detected_at":now.isoformat(),
        "reference_price":price,"metadata":metadata,"outcomes":{},"paper_admission":False})
    return True


def evaluate(reg,observations,now):
    # A late/missing measurement is not replaced with today's price.
    for key,payload in reg.db.execute("SELECT id,payload FROM records WHERE kind='radar_call'").fetchall():
        call=json.loads(payload);age=(now-datetime.fromisoformat(call["detected_at"])).total_seconds()
        changed=False
        for horizon,seconds in HORIZONS.items():
            if horizon in call["outcomes"] or age<seconds:continue
            price=observations.get(call["market"]+":"+call["identity"])
            if age>seconds+600:
                call["outcomes"][horizon]={"status":"missed_no_reconstruction"};changed=True
            elif price is not None and math.isfinite(float(price)) and float(price)>0:
                gross=(float(price)/call["reference_price"]-1)*100
                call["outcomes"][horizon]={"status":"observed","observed_at":now.isoformat(),"gross_change_pct":gross,
                    "estimated_net_pct":gross-.35 if call["market"]=="binance" else None,
                    "cost_policy":"0.35 percentage-point roundtrip assumption, not execution PnL" if call["market"]=="binance" else "unknown_gas_tax_route_impact_not_profit"}
                changed=True
        if changed:reg.put("radar_call",key,call)


def collect(reg,public,dex_rows,now=None):
    info,tickers=public("exchangeInfo"),public("ticker/24hr")
    # Timestamp AFTER receipt: a timestamp taken before the HTTP request can
    # incorrectly classify fresh ticker closeTime values as future data.
    now=now or datetime.now(timezone.utc)
    ranked=shortlist(info,tickers,now.timestamp()*1000)[:10]
    prices={}
    for item in tickers:
        try:
            p=float(item["lastPrice"]);age=now.timestamp()*1000-float(item["closeTime"])
            if math.isfinite(p) and p>0 and 0<=age<=120000:prices[item["symbol"]]=p
        except (ValueError,TypeError,KeyError):continue
    observations={"binance:"+s:p for s,p in prices.items()}
    for row in ranked:
        if row["symbol"] in prices:record(reg,"binance",row["symbol"],prices[row["symbol"]],now,row)
    dex=[]
    for row in dex_rows:
        if not row.get("chain") or not row.get("pair"):continue
        identity=row["chain"]+":"+row["pair"]
        try:p=float(row.get("price_usd"))
        except (ValueError,TypeError):continue
        if not math.isfinite(p) or p<=0:continue
        observations["dex:"+identity]=p
        metadata={k:row.get(k) for k in ("chain","token_address","pair","liquidity","volume","change","risk","security")}
        record(reg,"dex",identity,p,now,metadata)
        dex.append({**metadata,"price_usd":p,"binance_executable":False,"paper_admission":False})
    evaluate(reg,observations,now)
    calls=[json.loads(r[0]) for r in reg.db.execute("SELECT payload FROM records WHERE kind='radar_call'")]
    outcomes={h:{"observed":sum(c["outcomes"].get(h,{}).get("status")=="observed" for c in calls),
        "missed":sum(c["outcomes"].get(h,{}).get("status")=="missed_no_reconstruction" for c in calls)} for h in HORIZONS}
    return {"version":"opportunity_radar_v1","as_of":now.isoformat(),"binance":ranked,"dex":dex,
        "recorded_calls":len(calls),"outcomes":outcomes,"recent_calls":sorted(calls,key=lambda c:c["detected_at"],reverse=True)[:20],
        "policy":"One detection per market/identity/UTC day; includes failures; momentum heuristic, not whale proof or buy advice",
        "paper_admission":False,"sources":["Binance public","DEXScreener observations"]}
