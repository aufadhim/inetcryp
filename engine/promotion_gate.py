"""Safety gate for promoting paper results to live trading."""
from datetime import datetime, timezone
from typing import Any, Dict


def evaluate_promotion(summary: Dict[str, Any]) -> Dict[str, Any]:
    history = summary.get("history", [])
    wins = [x for x in history if float(x.get("pnl_usd", 0)) > 0]
    losses = [x for x in history if float(x.get("pnl_usd", 0)) <= 0]
    gross_profit = sum(float(x.get("pnl_usd", 0)) for x in wins)
    gross_loss = abs(sum(float(x.get("pnl_usd", 0)) for x in losses))
    profit_factor = gross_profit / gross_loss if gross_loss else (999.0 if gross_profit else 0.0)
    win_rate = len(wins) / len(history) * 100 if history else 0.0
    reasons = []
    if len(history) < 200:
        reasons.append(f"butuh minimal 200 closed trades ({len(history)}/200)")
    if win_rate < 55:
        reasons.append(f"win rate {win_rate:.1f}% di bawah 55%")
    if profit_factor < 1.3:
        reasons.append(f"profit factor {profit_factor:.2f} di bawah 1.30")
    if float(summary.get("net_return_pct", 0)) <= 0:
        reasons.append("net return paper belum positif")
    strategy_count = len({x.get("strategy", "unknown") for x in history})
    if history and (strategy_count != 1 or any(not x.get("strategy") for x in history)):
        reasons.append("sample harus berasal dari satu strategi terversi yang konsisten")
    timestamps = []
    for trade in history:
        try:
            timestamps.append(datetime.fromisoformat(trade["exit_time"]))
        except (KeyError, TypeError, ValueError):
            pass
    forward_days = ((max(timestamps) - min(timestamps)).total_seconds() / 86400) if len(timestamps) >= 2 else 0
    if forward_days < 30:
        reasons.append(f"butuh minimal 30 hari forward paper ({forward_days:.1f}/30)")
    if "max_drawdown_pct" in summary:
        max_drawdown = float(summary["max_drawdown_pct"])
    else:
        equity = peak = float(summary.get("initial_balance", 1000.0))
        max_drawdown = 0.0
        for trade in history:
            equity += float(trade.get("pnl_usd", 0))
            peak = max(peak, equity)
            if peak > 0:
                max_drawdown = max(max_drawdown, (peak - equity) / peak * 100)
    if max_drawdown > 10:
        reasons.append(f"max drawdown {max_drawdown:.2f}% di atas 10% atau belum tersedia")
    max_consecutive_losses = 0
    current = 0
    for trade in history:
        if float(trade.get("pnl_usd", 0)) <= 0:
            current += 1
            max_consecutive_losses = max(max_consecutive_losses, current)
        else:
            current = 0
    if max_consecutive_losses > 5:
        reasons.append(f"consecutive loss maksimum {max_consecutive_losses} > 5")
    return {"ready_for_live": not reasons, "closed_trades": len(history), "win_rate_pct": round(win_rate, 2), "profit_factor": round(profit_factor, 2), "forward_days": round(forward_days, 1), "max_drawdown_pct": max_drawdown, "max_consecutive_losses": max_consecutive_losses, "reasons": reasons or ["paper gate lulus; tetap mulai live dengan ukuran minimum"]}
