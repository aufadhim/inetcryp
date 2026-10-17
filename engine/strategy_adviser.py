"""Gemini adviser for diagnosing paper strategy failures; advisory only."""
import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict
from engine.ai_chat import chat_with_gemini, is_failure


def advise_after_losses(summary: Dict[str, Any]) -> str:
    history = summary.get("history", [])
    recent = history[-8:]
    losses = [trade for trade in recent if float(trade.get("pnl_usd", 0)) < 0]
    if len(losses) < 3:
        return ""
    if os.path.exists("data/advisor_latest.json"):
        try:
            with open("data/advisor_latest.json", "r", encoding="utf-8") as handle:
                previous = json.load(handle)
            created = datetime.fromisoformat(previous.get("created_at", "")).timestamp()
            if previous.get("ok") is True and time.time() - created < 6 * 3600:
                return ""
        except Exception:
            pass
    failure_path = "data/advisor_failure.json"
    if os.path.exists(failure_path):
        try:
            with open(failure_path, "r", encoding="utf-8") as handle:
                failed = json.load(handle)
            if time.time() - datetime.fromisoformat(failed["created_at"]).timestamp() < 30 * 60:
                return ""
        except Exception:
            pass
    slim_portfolio = {k: summary.get(k) for k in ("equity", "net_pnl_usd", "net_return_pct",
        "closed_trades_count", "win_rate_pct", "open_positions_count")}
    context = {"recent_trades": recent[-5:], "paper_portfolio": slim_portfolio,
        "candidate_strategies": ["ema_trend", "rsi_mean_reversion", "volatility_breakout", "vwap_reversion"]}
    advice = chat_with_gemini("Tiga atau lebih trade paper terakhir rugi. Diagnosis dan pilih satu eksperimen konservatif. Jangan mengubah strategi otomatis.", context, operation="strategy_adviser")
    if is_failure(advice):
        temp_failure = failure_path + ".tmp"
        with open(temp_failure, "w", encoding="utf-8") as handle:
            json.dump({"created_at": datetime.now(timezone.utc).isoformat(), "ok": False}, handle)
        os.replace(temp_failure, failure_path)
        return ""
    os.makedirs("data", exist_ok=True)
    temp = "data/advisor_latest.json.tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump({"created_at": datetime.now(timezone.utc).isoformat(), "ok": True, "advice": advice}, handle, ensure_ascii=False, indent=2)
    os.replace(temp, "data/advisor_latest.json")
    return advice
