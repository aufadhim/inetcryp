"""Historical replay through the actual paper engine, never a live account."""
from dataclasses import dataclass
import pandas as pd
from engine.paper_trader import CryptoPaperTrader
from engine.intraday import STRATEGY


@dataclass
class ReplayClient:
    frame: pd.DataFrame
    cursor: int = 100

    def get_klines(self, symbol, interval="15m", limit=201):
        # Only completed history and the new candle's OPEN are observable.
        result = self.frame.iloc[max(0, self.cursor-limit+1):self.cursor+1].copy()
        for col in ("High", "Low", "Close"):
            result.iloc[-1, result.columns.get_loc(col)] = result.iloc[-1]["Open"]
        for col in ("Volume", "QuoteVolume", "Trades", "CVD_Delta"):
            if col in result:
                result.iloc[-1, result.columns.get_loc(col)] = 0
        return result


def replay(frame, symbol="BTCUSDT", timeframe="15m", initial_capital=1000,
           fee_pct=0.1, slippage_pct=0.05, tp_pct=3, sl_pct=1.5,
           max_allocation=50, start_index=100, fast=False):
    if len(frame) <= max(100, start_index):
        return {"error": "At least 101 chronological candles are required."}
    if not isinstance(frame.index, pd.DatetimeIndex) or not frame.index.is_monotonic_increasing or frame.index.has_duplicates:
        raise ValueError("Replay requires unique ascending candle timestamps")
    if not (0 <= fee_pct < 100 and 0 <= slippage_pct < 100 and initial_capital > 0
            and max_allocation > 0 and tp_pct > 0 and 0 < sl_pct < 100):
        raise ValueError("Invalid replay risk or cost parameters")
    if frame[["Open", "High", "Low", "Close", "Volume"]].isna().any().any():
        raise ValueError("Missing OHLCV data")
    client = ReplayClient(frame)
    def clock():
        stamp = frame.index[client.cursor]
        return (stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")).to_pydatetime()
    trader = CryptoPaperTrader(client=client, persist=False, clock=clock)
    if fast:
        from engine.replay_features import ReplayFeatures
        features = ReplayFeatures(frame)
        trader.metrics_fn = lambda closed: features.at(client.cursor)
    trader.state.update(initial_balance=initial_capital, cash_usdt=initial_capital, equity=initial_capital)
    trader.fee_pct, trader.slippage_pct = fee_pct, slippage_pct
    trader.tp_pct, trader.sl_pct, trader.max_alloc = tp_pct, sl_pct, max_allocation
    # Freeze the research profile, independent of process environment overrides.
    trader.sl_plus_trigger_pct, trader.sl_plus_lock_pct = 0.6, 0.1
    trader.sl_plus_trail_pct, trader.max_hold_minutes, trader.cooldown_minutes = 0.5, 240, 30
    curve, peak, drawdown = [], float(initial_capital), 0.0
    for cursor in range(max(100, start_index), len(frame)):
        client.cursor = cursor
        summary = trader.run_eval_cycle([symbol], timeframe)["summary"]
        equity = summary["equity"]
        peak = max(peak, equity)
        drawdown = max(drawdown, (peak-equity)/peak*100)
        curve.append({"time": clock().isoformat(), "equity": equity})
    trades = trader.state["history"]
    gains = sum(t["pnl_usd"] for t in trades if t["pnl_usd"] > 0)
    losses = -sum(t["pnl_usd"] for t in trades if t["pnl_usd"] < 0)
    return {
        "symbol": symbol, "timeframe": timeframe, "strategy": STRATEGY,
        "accounting_version": "net_costs_v1", "execution_model": "next_open_sampled_paper_replay",
        "initial_capital": initial_capital, "final_capital": summary["equity"],
        "net_pnl_usd": summary["net_pnl_usd"], "net_pnl_pct": summary["net_return_pct"],
        "total_trades": len(trades), "winning_trades": sum(t["pnl_usd"] > 0 for t in trades),
        "losing_trades": sum(t["pnl_usd"] <= 0 for t in trades),
        "win_rate_pct": summary["win_rate_pct"], "profit_factor": gains/losses if losses else None,
        "max_drawdown_pct": drawdown, "open_positions_count": summary["open_positions_count"],
        "fee_pct_per_side": fee_pct, "slippage_pct_per_side": slippage_pct,
        "parameters": {"tp_pct": tp_pct, "sl_pct": sl_pct, "max_allocation": max_allocation,
            "sl_plus_trigger_pct": 0.6, "sl_plus_lock_pct": 0.1, "sl_plus_trail_pct": 0.5,
            "max_hold_minutes": 240, "cooldown_minutes": 30},
        "start": curve[0]["time"], "end": curve[-1]["time"],
        "equity_curve": curve, "trades": trades,
        "validation_status": "research_only",
        "warnings": ["One symbol, sampled at candle opens; intrabar stop touches are not simulated.",
            "Open positions remain marked at estimated net liquidation value, not counted as closed wins.",
            "Historical results do not establish live profitability; frozen out-of-sample and forward testing required."]
    }
