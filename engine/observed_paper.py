"""Paper fills from orderbooks actually received at decision time. No order submission."""
import math
from datetime import datetime, timezone
import pandas as pd
from engine.research_lab import account

MODEL="observed_depth_v1"


def depth_fill(levels, *, quote=None, quantity=None):
    if (quote is None)==(quantity is None):raise ValueError("Specify one target")
    remaining=float(quote if quote is not None else quantity)
    if remaining<=0 or not math.isfinite(remaining):raise ValueError("Invalid size")
    cash=units=0.0
    for price,size,*_ in levels:
        price,size=float(price),float(size)
        if not all(math.isfinite(v) and v>0 for v in (price,size)):raise ValueError("Invalid depth")
        take=min(size,remaining/price if quote is not None else remaining)
        units+=take;cash+=take*price
        remaining-=take*price if quote is not None else take
        if remaining<=1e-8:return {"price":cash/units,"quantity":units,"notional":cash}
    return None  # All-or-none paper assumption; no fabricated liquidity.


def check_quote(book, now):
    try:
        received=pd.Timestamp(book["received_at"])
        age=(pd.Timestamp(now)-received).total_seconds()
        latency=float(book["latency_ms"])
        bids=book["bids"];asks=book["asks"]
        bid=float(bids[0][0]);ask=float(asks[0][0])
        if (not all(math.isfinite(v) for v in (age,latency,bid,ask)) or not 0<=age<=5
                or not 0<=latency<=5000 or not 0<bid<=ask):return "stale_or_invalid_quote"
        if (ask-bid)/((ask+bid)/2)>.002:return "spread_too_wide"
        if any(float(bids[i][0])<float(bids[i+1][0]) for i in range(len(bids)-1)):return "unsorted_depth"
        if any(float(asks[i][0])>float(asks[i+1][0]) for i in range(len(asks)-1)):return "unsorted_depth"
        if any(not math.isfinite(float(v)) or float(v)<=0 for side in (bids,asks) for level in side for v in level[:2]):return "invalid_depth"
        return None
    except (ValueError,KeyError,TypeError,IndexError):return "invalid_quote"


def observed_step(state,candidate,observations,now=None,fee=.001,allow_entry=True):
    now=pd.Timestamp(now or datetime.now(timezone.utc))
    if now.tzinfo is None:raise ValueError("Timezone required")
    now=now.tz_convert("UTC");at=now.isoformat()
    state.setdefault("execution_model",MODEL)
    if state["execution_model"]!=MODEL:raise ValueError("Execution model mismatch")
    events=[];marks={};observed_candles=[]
    state.setdefault("realized_days",{})
    for symbol,observation in sorted(observations.items()):
        book=observation["book"]
        error=check_quote(book,now)
        if error:
            events.append({"symbol":symbol,"status":"rejected","reason":error});continue
        closed=pd.Timestamp(observation["candle_at"])
        if closed.tzinfo is None or closed+pd.Timedelta(minutes=15)>now:
            events.append({"symbol":symbol,"status":"rejected","reason":"unfinished_signal_candle"});continue
        observed_candles.append(closed.isoformat())
        pos=state["positions"].get(symbol)
        if pos:
            fill=depth_fill(book["bids"],quantity=pos["quantity"])
            if fill is None:
                events.append({"symbol":symbol,"status":"rejected","reason":"insufficient_exit_depth"});continue
            net=fill["notional"]*(1-fee)
            marks[symbol]=net
            age=(now-pd.Timestamp(pos["entry_time"])).total_seconds()/60
            reason=None
            if fill["price"]<=pos["entry"]*(1-candidate.stop_pct/100):reason="observed_stop"
            elif fill["price"]>=pos["entry"]*(1+candidate.target_pct/100):reason="observed_target"
            elif age>=candidate.hold_bars*15:reason="observed_time_stop"
            if reason:
                pnl=net-pos["size"]
                state["cash"]+=net
                trade={"symbol":symbol,"strategy":candidate.id,"entry_time":pos["entry_time"],"exit_time":at,
                    "pnl_usd":pnl,"reason":reason,"execution_model":MODEL,"exit_price":fill["price"],
                    "quote_received_at":book["received_at"],"latency_ms":book["latency_ms"],
                    "gross_pnl_usd":pos["size"]*(fill["price"]/pos["reference_entry"]-1),
                    **{k:pos.get(k,"unknown") for k in ("entry_regime","entry_hour_utc","entry_volatility")}}
                state["trades"].append(trade)
                day=at[:10];state["realized_days"][day]=state["realized_days"].get(day,0)+pnl
                del state["positions"][symbol];marks.pop(symbol,None)
                events.append({"symbol":symbol,"status":"closed",**trade})
            continue  # Cannot re-enter on the same observed quote.
        candle=closed.isoformat()
        if state["seen"].get(symbol)==candle:continue
        state["seen"][symbol]=candle
        if not observation.get("signal") or not allow_entry:continue
        signal_age=(now-(closed+pd.Timedelta(minutes=15))).total_seconds()
        if not 0<=signal_age<=90:
            events.append({"symbol":symbol,"status":"rejected","reason":"late_signal","signal_age_seconds":signal_age});continue
        if state["realized_days"].get(at[:10],0)<=-10 or len(state["positions"])>=5 or state["cash"]<50:continue
        fill=depth_fill(book["asks"],quote=50/(1+fee))
        if fill is None:
            events.append({"symbol":symbol,"status":"rejected","reason":"insufficient_entry_depth"});continue
        reference=float(book["asks"][0][0])
        if fill["price"]/reference-1>.001:
            events.append({"symbol":symbol,"status":"rejected","reason":"excessive_depth_impact"});continue
        mark=depth_fill(book["bids"],quantity=fill["quantity"])
        if mark is None:
            events.append({"symbol":symbol,"status":"rejected","reason":"insufficient_exit_depth"});continue
        state["cash"]-=50
        state["positions"][symbol]={"entry":fill["price"],"quantity":fill["quantity"],"size":50,"entry_time":at,
            "reference_entry":reference,"entry_regime":observation.get("regime","unknown"),"entry_hour_utc":now.hour,
            "entry_volatility":observation.get("volatility","unknown"),"execution_model":MODEL,
            "signal_candle":candle,"quote_received_at":book["received_at"],"latency_ms":book["latency_ms"]}
        marks[symbol]=mark["notional"]*(1-fee)
        events.append({"symbol":symbol,"status":"opened","fill_price":fill["price"],"decision_at":at,
                       "signal_candle":candle,"quote_received_at":book["received_at"],"latency_ms":book["latency_ms"]})
    # Mark unquoted positions conservatively using their last observed valuation.
    state["valuation_complete"]=all(symbol in marks for symbol in state["positions"])
    for symbol,pos in state["positions"].items():
        if symbol in marks:pos["last_liquidation_value"]=marks[symbol]
        else:marks[symbol]=pos.get("last_liquidation_value",0)
    if observed_candles:
        latest=max(observed_candles)
        if state.get("last_observed_candle")!=latest:
            state["observed_steps"]=state.get("observed_steps",0)+1
            state["last_observed_candle"]=latest
        state["first_at"]=state["first_at"] or at
        state["last_at"]=at
        equity=state["cash"]+sum(marks.values())
        state["equity"]=equity;state["peak"]=max(state["peak"],equity)
        state["max_drawdown_pct"]=max(state["max_drawdown_pct"],(state["peak"]-equity)/state["peak"]*100)
        state.setdefault("equity_curve",[]).append({"at":at,"equity":equity})
    return events
