"""Causal backtest for post-downtrend compression breakouts."""
from __future__ import annotations

from typing import Any, Dict
import pandas as pd

from engine.compression_screener import analyze_compression


def backtest_compression(frame: pd.DataFrame, symbol: str, *, initial_capital=1000.0,
                         fee_pct=0.1, slippage_pct=0.05, risk_pct=0.25,
                         reward_r=2.0, max_hold_bars=18) -> Dict[str, Any]:
    if len(frame) < 110:
        return {"symbol": symbol, "error": "insufficient_history"}
    cash, peak, max_dd = float(initial_capital), float(initial_capital), 0.0
    position, trades = None, []
    for i in range(101, len(frame)):
        bar = frame.iloc[i]
        if position:
            position["bars"] += 1
            exit_price, reason = None, None
            # Conservative same-bar ordering: stop is assumed hit before target.
            if float(bar.Low) <= position["stop"]:
                exit_price, reason = position["stop"], "stop"
            elif float(bar.High) >= position["target"]:
                exit_price, reason = position["target"], "target"
            elif position["bars"] >= max_hold_bars:
                exit_price, reason = float(bar.Close), "time"
            if exit_price is not None:
                sell = exit_price * (1-slippage_pct/100)
                gross = position["qty"] * sell
                proceeds = gross * (1-fee_pct/100)
                pnl = proceeds-position["cost"]
                cash += proceeds
                trades.append({"entry_time": str(position["time"]), "exit_time": str(frame.index[i]),
                    "entry": position["entry"], "exit": exit_price, "pnl_usd": round(pnl, 6),
                    "pnl_r": round(pnl/max(position["risk_usd"], 1e-12), 4), "reason": reason})
                position = None
        if position is None:
            setup = analyze_compression(symbol, frame.iloc[:i+1])
            if setup and setup["status"] == "BREAKOUT_CONFIRMED":
                entry = float(bar.Open) * (1+slippage_pct/100)
                stop = float(setup["support"])
                risk_per_unit = entry-stop
                if risk_per_unit <= 0 or risk_per_unit/entry > 0.08:
                    continue
                risk_usd = cash*risk_pct/100
                notional = min(cash, risk_usd/(risk_per_unit/entry))
                if notional <= 0:
                    continue
                qty = notional*(1-fee_pct/100)/entry
                cash -= notional
                position = {"time": frame.index[i], "entry": entry, "stop": stop,
                    "target": entry+reward_r*risk_per_unit, "qty": qty, "cost": notional,
                    "risk_usd": risk_usd, "bars": 0}
        equity = cash
        if position:
            equity += position["qty"]*float(bar.Close)*(1-slippage_pct/100)*(1-fee_pct/100)
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak-equity)/peak*100)
    if position:
        bar = frame.iloc[-1]
        proceeds = position["qty"]*float(bar.Close)*(1-slippage_pct/100)*(1-fee_pct/100)
        pnl = proceeds-position["cost"]
        cash += proceeds
        trades.append({"entry_time": str(position["time"]), "exit_time": str(frame.index[-1]),
            "entry": position["entry"], "exit": float(bar.Close), "pnl_usd": round(pnl, 6),
            "pnl_r": round(pnl/max(position["risk_usd"], 1e-12), 4), "reason": "end"})
    wins = [t for t in trades if t["pnl_usd"] > 0]
    losses = [t for t in trades if t["pnl_usd"] <= 0]
    gp = sum(t["pnl_usd"] for t in wins)
    gl = abs(sum(t["pnl_usd"] for t in losses))
    return {"symbol": symbol, "strategy": "post_downtrend_compression_v1",
        "initial_capital": initial_capital, "final_capital": round(cash, 2),
        "net_pnl_usd": round(cash-initial_capital, 2), "total_trades": len(trades),
        "win_rate_pct": round(len(wins)/len(trades)*100, 2) if trades else 0.0,
        "profit_factor": round(gp/gl, 3) if gl else (999.0 if gp else 0.0),
        "max_drawdown_pct": round(max_dd, 3), "fee_pct_per_side": fee_pct,
        "slippage_pct_per_side": slippage_pct, "trades": trades}


def walk_forward(frame: pd.DataFrame, symbol: str) -> Dict[str, Any]:
    cut = int(len(frame)*0.7)
    development = backtest_compression(frame.iloc[:cut], symbol)
    holdout = backtest_compression(frame.iloc[max(0, cut-100):], symbol)
    eligible = (development.get("total_trades", 0) >= 20 and holdout.get("total_trades", 0) >= 8
        and development.get("profit_factor", 0) >= 1.2 and holdout.get("profit_factor", 0) >= 1.2
        and development.get("net_pnl_usd", 0) > 0 and holdout.get("net_pnl_usd", 0) > 0
        and holdout.get("max_drawdown_pct", 99) <= 5)
    return {"symbol": symbol, "development": development, "holdout": holdout,
        "eligible_for_challenger_paper": eligible}
