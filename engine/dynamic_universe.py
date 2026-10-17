"""Forward-only public spot universe. Rankings are research heuristics, not buys."""
import json
import math
import time
from pathlib import Path
from datetime import datetime, timezone
import requests

VERSION = "liquid_momentum_v1"
STABLES = {"USDC", "FDUSD", "TUSD", "USDP", "DAI", "USDD", "USD1", "EUR", "EURI", "PAXG", "WBTC"}


def shortlist(info, tickers, now_ms):
    eligible = {x["symbol"] for x in info.get("symbols", [])
        if x.get("status") == "TRADING" and x.get("quoteAsset") == "USDT"
        and x.get("isSpotTradingAllowed") is True and x.get("baseAsset") not in STABLES
        and not x.get("baseAsset", "").endswith(("UP", "DOWN", "BULL", "BEAR"))}
    rows = []
    for item in tickers:
        try:
            volume, change, count, price, closed = [float(item[k]) for k in
                ("quoteVolume", "priceChangePercent", "count", "lastPrice", "closeTime")]
            if not all(math.isfinite(v) for v in (volume, change, count, price, closed)):
                continue
            if item["symbol"] not in eligible or not 0 <= now_ms-closed <= 120000:
                continue
            if volume < 5_000_000 or count < 5000 or price <= 0 or not 0 < change <= 25:
                continue
            # Bounded momentum with liquidity contribution; no whale claims.
            score = min(change, 15)*2 + min(math.log10(volume/5_000_000+1)*10, 20)
            rows.append({"symbol": item["symbol"], "score": round(score, 4),
                         "change_24h_pct": change, "quote_volume_24h": volume})
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(rows, key=lambda r: (-r["score"], r["symbol"]))[:30]


def liquidity(book):
    try:
        bids = [(float(p), float(q)) for p,q in book["bids"]]
        asks = [(float(p), float(q)) for p,q in book["asks"]]
        if not bids or not asks or not all(math.isfinite(x) and x > 0 for pair in bids+asks for x in pair):
            return None
        bid, ask = max(p for p,q in bids), min(p for p,q in asks)
        mid = (bid+ask)/2
        spread = (ask-bid)/mid*100
        buy_depth = sum(p*q for p,q in bids if p >= mid*0.995)
        sell_depth = sum(p*q for p,q in asks if p <= mid*1.005)
        if not 0 <= spread <= 0.2 or min(buy_depth, sell_depth) < 25000:
            return None
        return {"spread_pct": round(spread, 5), "bid_depth_usdt": round(buy_depth, 2),
                "ask_depth_usdt": round(sell_depth, 2)}
    except (KeyError, ValueError, TypeError):
        return None


class DynamicUniverse:
    def __init__(self):
        self.session = requests.Session()  # no app credentials, signed API or dotenv
        self.cached = None
        self.checked_at = 0

    def get(self, path, **params):
        response = self.session.get("https://data-api.binance.vision/api/v3/"+path,
                                    params=params, timeout=8)
        response.raise_for_status()
        return response.json()

    def select(self):
        now = time.time()
        if self.cached and now-self.checked_at < (900 if self.cached["status"] == "ok" else 60):
            return self.cached
        snapshot = {"version": VERSION, "as_of": datetime.now(timezone.utc).isoformat(),
                    "status": "ok", "candidates": [], "symbols": [],
                    "note": "Forward screener, not a buy signal or historical universe."}
        try:
            info, tickers = self.get("exchangeInfo"), self.get("ticker/24hr")
            ranked = shortlist(info, tickers, time.time()*1000)
            snapshot["shortlisted_count"] = len(ranked)
            for row in ranked:
                if time.time()-now > 45:
                    raise TimeoutError("Screening budget exhausted")
                detail = liquidity(self.get("depth", symbol=row["symbol"], limit=100))
                if detail:
                    snapshot["candidates"].append({**row, **detail})
                if len(snapshot["candidates"]) >= 10:
                    break
            snapshot["symbols"] = [x["symbol"] for x in snapshot["candidates"]]
        except Exception as exc:
            # Fail closed for new entries; existing positions still get managed.
            snapshot.update(status="unavailable", symbols=[], candidates=[], error_type=type(exc).__name__)
        self.cached, self.checked_at = snapshot, now
        folder = Path("data/universe")
        folder.mkdir(parents=True, exist_ok=True)
        text = json.dumps(snapshot, indent=2, allow_nan=False)
        temp = folder/"latest.tmp"
        temp.write_text(text, encoding="utf-8")
        temp.replace(folder/"latest.json")
        (folder/(datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")+".json")).write_text(text, encoding="utf-8")
        return snapshot


def latest_snapshot():
    try:
        data = json.loads(Path("data/universe/latest.json").read_text(encoding="utf-8"))
        age = (datetime.now(timezone.utc)-datetime.fromisoformat(data["as_of"])).total_seconds()
        data["stale"] = not 0 <= age <= 1200
        return data
    except (OSError, ValueError, KeyError):
        return {"status": "unavailable", "stale": True, "symbols": [], "candidates": []}
