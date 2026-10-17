"""Frozen small candidate experiment; never changes the running paper strategy."""
import os
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
import argparse
import json
import time
from pathlib import Path
import pandas as pd
from engine.historical_data import historical
from engine.paper_replay import replay

CANDIDATES = {"baseline": {"tp_pct": 3, "sl_pct": 1.5},
              "tight_exit": {"tp_pct": 1.5, "sl_pct": 1},
              "balanced_exit": {"tp_pct": 2, "sl_pct": 1.5}}


def compact(result):
    return {k:v for k,v in result.items() if k not in ("equity_curve", "trades")}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--end", default="2026-10-06T00:00:00Z")
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    args = parser.parse_args()
    if not 10 <= args.days <= 730:
        parser.error("days must be 10..730")
    end = pd.Timestamp(args.end)
    start = end-pd.Timedelta(days=args.days)
    started = time.perf_counter()
    stamp = pd.Timestamp.now(tz="UTC").strftime("%Y%m%dT%H%M%S%f")
    out = Path("data/research") / ("candidates-"+stamp)
    out.mkdir(parents=True)
    plan = {"candidates": CANDIDATES, "split": "60% development / 20% validation / 20% final holdout",
        "selection": "highest development net PnL only; all periods start flat",
        "gate": "validation and double-cost validation positive, validation >=30 closed trades, drawdown <=5%; final holdout also positive with >=30 trades",
        "days": args.days, "start": str(start), "end": str(end), "symbols": args.symbols,
        "warning": "Three predeclared risk variants, not a broad strategy search. Separate-symbol research, not a portfolio. No automatic promotion."}
    (out/"plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    rows = []
    for symbol in args.symbols:
        try:
            frame, provenance = historical(symbol, start, end)
            print(json.dumps({"symbol": symbol, "downloaded_bars": len(frame)}), flush=True)
            # Benchmark old and optimized engine on identical input and outputs.
            benchmark = {}
            for mode in (False, True):
                tick = time.perf_counter()
                result = replay(frame.iloc[:300], symbol, fast=mode)
                benchmark["fast_seconds" if mode else "reference_seconds"] = time.perf_counter()-tick
                if mode:
                    if result["trades"] != reference["trades"] or result["equity_curve"] != reference["equity_curve"]:
                        raise RuntimeError("Fast/reference mismatch; research aborted")
                else:
                    reference = result
            a, b = int(len(frame)*0.6), int(len(frame)*0.8)
            development = {}
            for name, params in CANDIDATES.items():
                result = replay(frame.iloc[:a], symbol, fast=True, **params)
                development[name] = compact(result)
                print(json.dumps({"symbol": symbol, "phase": "development", "candidate": name,
                                  "net": result["net_pnl_usd"], "trades": result["total_trades"]}), flush=True)
            selected = max(development, key=lambda name: development[name]["net_pnl_usd"])
            params = CANDIDATES[selected]
            validation = replay(frame.iloc[:b], symbol, start_index=a, fast=True, **params)
            stress = replay(frame.iloc[:b], symbol, start_index=a, fast=True, fee_pct=0.2, slippage_pct=0.1, **params)
            # The final holdout never affects selection or parameter changes.
            holdout = replay(frame, symbol, start_index=b, fast=True, **params)
            eligible = (validation["net_pnl_usd"] > 0 and stress["net_pnl_usd"] > 0
                and validation["total_trades"] >= 30 and validation["max_drawdown_pct"] <= 5
                and holdout["net_pnl_usd"] > 0 and holdout["total_trades"] >= 30
                and holdout["max_drawdown_pct"] <= 5)
            row = {"symbol": symbol, "dataset": provenance, "benchmark": benchmark,
                "development": development, "selected_on_development_only": selected,
                "validation": compact(validation), "double_cost_validation": compact(stress),
                "final_holdout": compact(holdout), "eligible_for_further_paper_review": eligible}
            (out/(symbol+"-holdout.json")).write_text(json.dumps(holdout, indent=2, allow_nan=False), encoding="utf-8")
            rows.append(row)
            print(json.dumps({"symbol": symbol, "selected": selected, "holdout_net": holdout["net_pnl_usd"],
                "eligible": eligible, "speedup": benchmark["reference_seconds"]/benchmark["fast_seconds"]}), flush=True)
        except Exception as exc:
            rows.append({"symbol": symbol, "error_type": type(exc).__name__, "status": "failed_no_promotion"})
            print(json.dumps(rows[-1]), flush=True)
        (out/"summary.json").write_text(json.dumps({"plan": plan, "results": rows,
            "elapsed_seconds": time.perf_counter()-started}, indent=2, allow_nan=False), encoding="utf-8")
    print(str((out/"summary.json").resolve()), flush=True)


if __name__ == "__main__":
    main()
