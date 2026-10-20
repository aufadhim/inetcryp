"""Timestamped public research inputs; unavailable fields never become zero evidence."""
import math
import os
from datetime import datetime, timezone
import requests


def fetch_json(url, params=None, headers=None):
    response = requests.get(url, params=params, headers=headers or {}, timeout=12)
    response.raise_for_status()
    return response.json()


def finite(value):
    try:
        n=float(value)
        return n if math.isfinite(n) else None
    except (ValueError,TypeError):
        return None


def coin_metadata():
    headers={}
    key=os.getenv("COINGECKO_DEMO_API_KEY","").strip()
    if key:
        headers["x-cg-demo-api-key"]=key
    raw=fetch_json("https://api.coingecko.com/api/v3/coins/markets",
        {"vs_currency":"usd","order":"market_cap_desc","per_page":250,"page":1,"sparkline":"false"},headers)
    if not isinstance(raw,list):
        raise ValueError("Unexpected CoinGecko payload")
    rows=[]
    for row in raw:
        if not row.get("id"):
            continue
        rows.append({"id":row["id"],"symbol":row.get("symbol"),"market_cap":finite(row.get("market_cap")),
            "fdv":finite(row.get("fully_diluted_valuation")),"circulating_supply":finite(row.get("circulating_supply")),
            "total_supply":finite(row.get("total_supply")),"max_supply":finite(row.get("max_supply")),
            "volume_24h":finite(row.get("total_volume")),"source_updated_at":row.get("last_updated"),
            "identity_policy":"CoinGecko ID only; no automatic ticker-to-contract match"})
    return {"status":"ok","coins":rows,"coverage":"top_250_market_cap","key_configured":bool(key)}


def derivatives(symbol):
    host="https://fapi.binance.com"
    output={"symbol":symbol,"sources":{}}
    for name,path,params in (
        ("funding","/fapi/v1/fundingRate",{"symbol":symbol,"limit":100}),
        ("open_interest","/futures/data/openInterestHist",{"symbol":symbol,"period":"15m","limit":96})):
        try:
            rows=fetch_json(host+path,params)
            if not isinstance(rows,list):
                raise ValueError("Expected time series")
            output["sources"][name]={"status":"ok","rows":rows}
        except (requests.RequestException,ValueError) as exc:
            output["sources"][name]={"status":"unavailable","error_type":type(exc).__name__}
    return output


def dex_risk(pair):
    """Market filters only; contract/holder safety remains explicitly unverified."""
    liquidity=finite((pair.get("liquidity") or {}).get("usd"))
    volume=finite((pair.get("volume") or {}).get("h24"))
    fdv=finite(pair.get("fdv"))
    created=finite(pair.get("pairCreatedAt"))
    age=(datetime.now(timezone.utc).timestamp()*1000-created)/3600000 if created else None
    tx=(pair.get("txns") or {}).get("h24") or {}
    sells=finite(tx.get("sells"))
    reasons=[]
    if liquidity is None or liquidity<50000: reasons.append("missing_or_thin_liquidity")
    if volume is None or volume<100000: reasons.append("insufficient_volume")
    if age is None or age<24: reasons.append("missing_age_or_younger_than_24h")
    if sells is None or sells<20: reasons.append("sell_activity_unproven")
    if fdv and liquidity is not None and liquidity/fdv<.02: reasons.append("low_liquidity_to_fdv")
    return {"market_filters_pass":not reasons,"reasons":reasons,"liquidity_usd":liquidity,
        "age_hours":age,"contract_security":"unverified","holder_concentration":"unverified",
        "sell_simulation":"unverified","eligible_for_paper":False}


def asof_observation(observations, decision_at):
    """Only receipt time counts, even when a provider reports an earlier event time."""
    from pandas import Timestamp
    decision=Timestamp(decision_at)
    if decision.tzinfo is None:
        raise ValueError("Timezone required")
    allowed=[row for row in observations if Timestamp(row["observed_at"])<=decision]
    return max(allowed,key=lambda row:Timestamp(row["observed_at"])) if allowed else None


def token_security(chain, address):
    chains={"ethereum":"1","bsc":"56","polygon":"137","arbitrum":"42161","base":"8453"}
    if chain=="solana":
        endpoint="https://api.gopluslabs.io/api/v1/solana/token_security"
    elif chain in chains:
        endpoint="https://api.gopluslabs.io/api/v1/token_security/"+chains[chain]
    else:
        return {"status":"unsupported_chain","eligible_for_paper":False}
    try:
        payload=fetch_json(endpoint,{"contract_addresses":address})
        if payload.get("code")!=1:
            return {"status":"provider_rejected","eligible_for_paper":False}
        result=payload.get("result") or {}
        info=result.get(address) or (result.get(address.lower()) if chain!="solana" else None)
        if not isinstance(info,dict) or not info:
            return {"status":"unknown_token","eligible_for_paper":False}
        checked,flags=[],[]
        for field in ("is_honeypot","cannot_sell_all","is_blacklisted","is_mintable","can_take_back_ownership","mintable","freezable"):
            value=info.get(field)
            if isinstance(value,dict):value=value.get("status")
            if str(value) in {"0","1"}:
                checked.append(field)
                if str(value)=="1":flags.append(field)
        holders=info.get("holders") or []
        percentages=[finite(holder.get("percent")) for holder in holders if isinstance(holder,dict)]
        percentages=[p for p in percentages if p is not None]
        top10=sum(sorted(percentages,reverse=True)[:10]) if percentages else None
        if top10 is not None and top10>.5:flags.append("top10_concentration_including_lp")
        return {"status":"observed","chain":chain,"token_address":address,"checked_fields":checked,"flags":flags,
            "top10_share_including_lp":top10,"eligible_for_paper":False,
            "limitation":"Third-party flags; swap sell simulation and historical execution are still required"}
    except (requests.RequestException,ValueError,TypeError,AttributeError) as exc:
        return {"status":"unavailable","error_type":type(exc).__name__,"eligible_for_paper":False}


def collect_sources(reg, symbols):
    """Independent sources fail independently, throttle expensive metadata to hourly."""
    now=datetime.now(timezone.utc)
    previous=reg.get("state","source_health",{})
    metadata=previous.get("coingecko",{})
    checked=metadata.get("observed_at")
    if not checked or (now-datetime.fromisoformat(checked)).total_seconds()>=3600:
        try:
            result=coin_metadata()
            received=datetime.now(timezone.utc).isoformat()
            reg.event("coingecko_observation",{"observed_at":received,**result})
            metadata={"status":"ok","coins":len(result["coins"]),"observed_at":received}
        except (requests.RequestException,ValueError) as exc:
            metadata={"status":"unavailable","error_type":type(exc).__name__,"observed_at":now.isoformat(),
                "action":"Check API availability or configure Demo key in service environment"}
    output={"coingecko":metadata,"derivatives":{}}
    for symbol in symbols[:3]:
        result=derivatives(symbol)
        counts={}
        for name,series in result["sources"].items():
            if series["status"]=="ok":
                counts[name]=reg.series(name,symbol,series["rows"],"fundingTime" if name=="funding" else "timestamp")
        reg.event("derivatives_observation",{"observed_at":datetime.now(timezone.utc).isoformat(),
            "symbol":symbol,"new_points":counts})
        output["derivatives"][symbol]={name:row["status"] for name,row in result["sources"].items()}
    output["observed_at"]=now.isoformat()
    reg.put("state","source_health",output)
    return output
