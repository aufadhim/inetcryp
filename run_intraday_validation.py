"""Public-data research run; disables dotenv before any application import."""
import os
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
import argparse
import json
from pathlib import Path
from datetime import datetime, timezone
from engine.binance_client import BinanceClient
from engine.paper_replay import replay


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    parser.add_argument("--bars", type=int, default=1000)
    args = parser.parse_args()
    if not 250 <= args.bars <= 1000:
        parser.error("Initial smoke test supports 250..1000 candles per symbol")
    client = BinanceClient()
    client.api_key = client.api_secret = ""
    client.session.headers.pop("X-MBX-APIKEY", None)
    results = []
    for symbol in args.symbols:
        frame = client.get_klines(symbol, "15m", args.bars).iloc[:-1]
        if len(frame) < 250:
            results.append({"symbol": symbol, "error": "Public history unavailable or insufficient"})
            continue
        # Frozen rules, no optimization; each evaluation segment starts flat.
        split = int(len(frame) * 0.7)
        discovery = replay(frame.iloc[:split], symbol)
        holdout = replay(frame, symbol, start_index=split)
        stress = replay(frame, symbol, start_index=split, fee_pct=0.2, slippage_pct=0.1)
        row = {"symbol": symbol, "development": discovery, "holdout": holdout, "double_cost_holdout": stress}
        results.append(row)
        print(json.dumps({"symbol": symbol, "holdout_trades": holdout["total_trades"],
            "holdout_net_usd": holdout["net_pnl_usd"], "holdout_drawdown_pct": holdout["max_drawdown_pct"],
            "double_cost_net_usd": stress["net_pnl_usd"]}), flush=True)
    out = Path("data/research")
    out.mkdir(parents=True, exist_ok=True)
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "status": "smoke_test_not_validation",
        "minimum_forward_plan": "8-12 weeks AND 200 closed cost-aware trades; extend if sample/regimes insufficient",
        "results": results}
    path = out / ("intraday-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + ".json")
    path.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(str(path.resolve()))


if __name__ == "__main__":
    main()
