"""Continuous, read-only compression strategy research worker."""
import os
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pandas as pd

from engine.binance_client import BinanceClient
from engine.compression_backtest import walk_forward
from engine.historical_data import historical


def atomic_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix+".tmp")
    temp.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
    temp.replace(path)


def cycle():
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    now = now.replace(hour=(now.hour//4)*4)
    client = BinanceClient()
    liquid = [x["symbol"] for x in client.get_top_tickers(limit=30)]
    symbols = list(dict.fromkeys(liquid + ["BTCUSDT", "ETHUSDT", "SOLUSDT", "ASTERUSDT"]))
    results = []
    for symbol in symbols:
        try:
            start = pd.Timestamp(now-timedelta(days=365)).floor("4h")
            frame, provenance = historical(symbol, start, pd.Timestamp(now),
                                           cache_dir="data/research/compression-cache", interval="4h")
            result = walk_forward(frame, symbol)
            result["dataset"] = provenance
            results.append(result)
        except Exception as exc:
            results.append({"symbol": symbol, "status": "failed", "error_type": type(exc).__name__})
    eligible = [r["symbol"] for r in results if r.get("eligible_for_challenger_paper")]
    payload = {"status": "ok", "strategy": "post_downtrend_compression_v1",
        "generated_at": now.isoformat(), "symbols_tested": len(results), "eligible": eligible,
        "promotion_policy": "research only; never changes paper strategy automatically", "results": results}
    atomic_json(Path("data/research/compression-latest.json"), payload)
    atomic_json(Path("data/compression_research_status.json"),
        {"status": "sleeping", "last_completed": now.isoformat(), "symbols_tested": len(results),
         "eligible_count": len(eligible), "next_run_hours": 4})


def main():
    while True:
        try:
            atomic_json(Path("data/compression_research_status.json"),
                {"status": "running", "started_at": datetime.now(timezone.utc).isoformat()})
            cycle()
        except Exception as exc:
            atomic_json(Path("data/compression_research_status.json"),
                {"status": "error", "error_type": type(exc).__name__,
                 "at": datetime.now(timezone.utc).isoformat()})
        time.sleep(4*60*60)


if __name__ == "__main__":
    main()
