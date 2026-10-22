"""Isolated prospective experiment, not a validated strategy or order executor."""
from datetime import datetime, timezone
import time

from engine.observed_paper import check_quote, depth_fill

VERSION = "anomaly_depth_paper_v1"
FEE = .001


def initial():
    return {"version": VERSION, "cash": 1000., "positions": {}, "trades": [],
            "seen": [], "live_trading": False, "promotion": False}


def step(state, calls, books, now):
    """Fixed protocol: $50, max five, 1.5% stop/3% target/2h expiry.

    Entries must be prospective, verified LONG calls, at most 90 seconds old.
    Missing exit quotes retain risk; never reconstruct a fill at a stop price.
    """
    if state["version"] != VERSION:
        raise ValueError("Unknown experimental protocol")
    events = []
    for symbol, pos in list(state["positions"].items()):
        book = books.get(symbol)
        if not book or check_quote(book, now):
            continue
        fill = depth_fill(book["bids"], quantity=pos["quantity"])
        if not fill:
            continue
        proceeds = fill["notional"] * (1-FEE)
        # Net liquidation value, not the gross price, activates SL+.
        if proceeds >= pos["cost"] * 1.01:
            pos["protected"] = True
        age = (now-datetime.fromisoformat(pos["opened_at"])).total_seconds()
        reason = ("stop" if proceeds <= pos["cost"]*.985 else
                  "target" if proceeds >= pos["cost"]*1.03 else
                  "sl_plus" if pos["protected"] and proceeds <= pos["cost"]*1.002 else
                  "time" if age >= 7200 else None)
        pos["liquidation_value"] = proceeds
        pos["marked_at"] = now.isoformat()
        if reason:
            trade = {**pos, "symbol": symbol, "closed_at": now.isoformat(),
                     "exit_price": fill["price"], "pnl_usd": proceeds-pos["cost"],
                     "reason": reason, "exit_received_at": book["received_at"]}
            state["trades"].append(trade)
            state["cash"] += proceeds
            del state["positions"][symbol]
            events.append({"status": "closed", **trade})
    closed_symbols = {e["symbol"] for e in events}
    daily_loss = sum(t["pnl_usd"] for t in state["trades"] if t["closed_at"][:10] == now.date().isoformat())
    for call in sorted(calls, key=lambda c: c["detected_at"]):
        entry = call["entry"]
        symbol = entry.get("binance_symbol")
        if call["id"] in state["seen"]:
            continue
        # Mark every encountered call once, including rejected/stale calls.
        state["seen"].append(call["id"])
        age = (now-datetime.fromisoformat(call["detected_at"])).total_seconds()
        if (entry.get("signal") != "LONG" or not entry.get("binance_spot_listing_verified")
                or not symbol or not 0 <= age <= 90):
            continue
        if (symbol in state["positions"] or symbol in closed_symbols or len(state["positions"]) >= 5
                or state["cash"] < 50 or daily_loss <= -10):
            continue
        book = books.get(symbol)
        if not book or check_quote(book, now):
            continue
        fill = depth_fill(book["asks"], quote=50/(1+FEE))
        if not fill:
            continue
        mark = depth_fill(book["bids"], quantity=fill["quantity"])
        if not mark or mark["notional"]*(1-FEE) < 50*.995:
            continue
        state["positions"][symbol] = {"call_id": call["id"], "quantity": fill["quantity"],
            "cost": 50., "entry_price": fill["price"], "opened_at": now.isoformat(),
            "entry_received_at": book["received_at"], "protected": False,
            "liquidation_value": mark["notional"]*(1-FEE), "marked_at": now.isoformat()}
        state["cash"] -= 50
        events.append({"status": "opened", "symbol": symbol, "call_id": call["id"]})
    state["as_of"] = now.isoformat()
    state["equity_last_observed"] = state["cash"] + sum(p["liquidation_value"] for p in state["positions"].values())
    state["stale_marks"] = sum((now-datetime.fromisoformat(p["marked_at"])).total_seconds() > 90 for p in state["positions"].values())
    state["realized_pnl"] = sum(t["pnl_usd"] for t in state["trades"])
    state["policy"] = "Experimental shadow only; observed depth + 0.1% fee/side; no latency/queue guarantee. SL+ can gap into loss. Not the main paper portfolio."
    return events


def cycle(reg, public, now=None):
    now = now or datetime.now(timezone.utc)
    state = reg.get("state", VERSION, None) or initial()
    import json
    calls = [json.loads(r[0]) for r in reg.db.execute("SELECT payload FROM records WHERE kind='anomaly_call'")]
    fresh = [c for c in calls if c["id"] not in state["seen"] and
             0 <= (now-datetime.fromisoformat(c["detected_at"])).total_seconds() <= 90]
    symbols = set(state["positions"])
    symbols.update(c["entry"]["binance_symbol"] for c in fresh if
                   c["entry"].get("signal") == "LONG" and c["entry"].get("binance_spot_listing_verified"))
    books = {}
    for symbol in sorted(symbols)[:10]:
        try:
            start = time.perf_counter()
            raw = public("depth", symbol=symbol, limit=20)
            books[symbol] = {"bids": raw["bids"], "asks": raw["asks"],
                            "received_at": datetime.now(timezone.utc).isoformat(),
                            "latency_ms": (time.perf_counter()-start)*1000}
        except Exception as exc:
            reg.event("anomaly_paper_quote_failed", {"symbol": symbol, "error_type": type(exc).__name__})
    events = step(state, calls, books, datetime.now(timezone.utc))
    reg.put("state", VERSION, state)
    for event in events:
        reg.event("anomaly_paper_fill", event)
    return state
