import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional
from engine.binance_client import BinanceClient
from engine.metrics import calculate_crypto_metrics


class CryptoBacktester:
    def __init__(self, client: Optional[BinanceClient] = None):
        self.client = client or BinanceClient()

    def run(
        self,
        symbol: str = "BTCUSDT",
        timeframe: str = "1h",
        strategy: str = "whale_slipstream",
        initial_capital: float = 1000.0,
        trade_allocation_pct: float = 25.0,
        tp_pct: float = 4.0,
        sl_pct: float = 2.0,
        limit_bars: int = 500,
        fee_pct: float = 0.1,
        slippage_pct: float = 0.05
    ) -> Dict[str, Any]:
        """Run quantitative strategy backtest on historical crypto klines."""
        clean_symbol = symbol.upper().replace("/", "")
        if strategy == "ema_pullback_v1":
            from engine.paper_replay import replay
            if limit_bars > 1000:
                if timeframe != "15m":
                    return {"error": "Long-history EMA replay currently supports 15m only"}
                from engine.historical_data import historical
                end = pd.Timestamp.now(tz="UTC").floor("15min")
                frame, dataset = historical(clean_symbol, end-pd.Timedelta(minutes=15*limit_bars), end)
            else:
                frame = self.client.get_klines(clean_symbol, interval=timeframe, limit=limit_bars).iloc[:-1]
                dataset = None
            result = replay(frame, clean_symbol, timeframe, initial_capital,
                            fee_pct, slippage_pct, tp_pct, sl_pct, fast=True)
            result["dataset"] = dataset
            return result
        if strategy not in {"whale_slipstream", "bullish_divergence", "markup_breakout"}:
            return {"error": "Unknown strategy"}
        df = self.client.get_klines(clean_symbol, interval=timeframe, limit=limit_bars)
        if df.empty or len(df) < 50:
            return {"error": "Insufficient historical candle data."}

        df_calc = calculate_crypto_metrics(df)

        capital = initial_capital
        position = None
        trades = []
        equity_curve = []

        for i in range(25, len(df_calc)):
            current = df_calc.iloc[i]
            prev = df_calc.iloc[i - 1]
            date_str = str(df_calc.index[i])
            curr_price = float(current["Close"])

            # 1. Manage Open Position
            if position:
                entry_price = position["entry_price"]
                # Conservative candle simulation: stop loss wins if both levels are touched.
                high_price = float(current["High"])
                low_price = float(current["Low"])
                tp_price = entry_price * (1 + tp_pct / 100.0)
                sl_price = entry_price * (1 - sl_pct / 100.0)
                if low_price <= sl_price:
                    exit_price = sl_price
                    pnl_pct = -sl_pct
                elif high_price >= tp_price:
                    exit_price = tp_price
                    pnl_pct = tp_pct
                else:
                    exit_price = curr_price
                    pnl_pct = ((exit_price * (1 - slippage_pct / 100.0) - entry_price) / entry_price) * 100
                high_since = max(position["highest_price"], float(current["High"]))
                position["highest_price"] = high_since

                exit_reason = None

                # Take Profit Hit
                if low_price <= sl_price:
                    exit_reason = f"SL Hit (-{sl_pct:.1f}%)"
                elif high_price >= tp_price:
                    exit_reason = f"TP Hit (+{tp_pct:.1f}%)"
                # Strategy Signals Exit
                elif strategy == "whale_slipstream" and current.get("Slipstream") == "SLIPSTREAM_BEAR":
                    exit_reason = "Slipstream Bear Cross"
                elif strategy == "bullish_divergence" and current.get("Divergence") == "BEARISH_DIVERGENCE":
                    exit_reason = "Whale Distribution Signal"

                if exit_reason:
                    # Apply round-trip trading costs to every exit path.
                    pnl_pct = pnl_pct - (fee_pct * 2)
                    trade_pnl_usd = position["size_usd"] * (pnl_pct / 100.0)
                    capital += trade_pnl_usd
                    trades.append({
                        "entry_time": position["entry_time"],
                        "exit_time": date_str,
                        "entry_price": entry_price,
                        "exit_price": exit_price,
                        "pnl_pct": round(pnl_pct, 2),
                        "pnl_usd": round(trade_pnl_usd, 2),
                        "reason": exit_reason
                    })
                    position = None

            # 2. Check Entry Condition
            elif position is None and capital > 50:
                is_entry = False

                if strategy == "whale_slipstream":
                    # LPM crosses above trigger line and not already deep premium
                    if current.get("Slipstream") == "SLIPSTREAM_BULL" and current.get("Dist_Bandar_Pct", 0) <= 3.5:
                        is_entry = True
                elif strategy == "bullish_divergence":
                    # Bullish divergence detected
                    if current.get("Divergence") == "BULLISH_DIVERGENCE" and current.get("Dist_Bandar_Pct", 0) <= 2.0:
                        is_entry = True
                elif strategy == "markup_breakout":
                    # High volume mark-up breakout
                    if current.get("Phase") == "MARK_UP" and current.get("Intensity", 0) >= 1.8 and curr_price > float(current.get("SMA20", 0)):
                        is_entry = True

                if is_entry:
                    size_usd = capital * (trade_allocation_pct / 100.0)
                    position = {
                        "entry_time": date_str,
                        "entry_price": curr_price * (1 + slippage_pct / 100.0),
                        "size_usd": size_usd,
                        "highest_price": curr_price
                    }

            # Record daily equity point
            equity_curve.append({
                "time": date_str[:16],
                "equity": round(capital, 2)
            })

        # Close open position at end
        if position:
            last = df_calc.iloc[-1]
            pnl_pct = ((float(last["Close"]) * (1 - slippage_pct / 100.0) - position["entry_price"]) / position["entry_price"]) * 100 - (fee_pct * 2)
            trade_pnl_usd = position["size_usd"] * (pnl_pct / 100.0)
            capital += trade_pnl_usd
            trades.append({
                "entry_time": position["entry_time"],
                "exit_time": str(df_calc.index[-1]),
                "entry_price": position["entry_price"],
                "exit_price": float(last["Close"]),
                "pnl_pct": round(pnl_pct, 2),
                "pnl_usd": round(trade_pnl_usd, 2),
                "reason": "End of Backtest Period"
            })

        # Calculate Summary Metrics
        total_trades = len(trades)
        wins = [t for t in trades if t["pnl_usd"] > 0]
        losses = [t for t in trades if t["pnl_usd"] <= 0]
        win_rate = round((len(wins) / total_trades * 100), 1) if total_trades > 0 else 0.0

        gross_profit = sum(t["pnl_usd"] for t in wins)
        gross_loss = abs(sum(t["pnl_usd"] for t in losses))
        profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)

        net_pnl_usd = round(capital - initial_capital, 2)
        net_pnl_pct = round((net_pnl_usd / initial_capital) * 100, 2)

        # Max drawdown
        peak = initial_capital
        max_dd = 0.0
        for pt in equity_curve:
            eq = pt["equity"]
            if eq > peak:
                peak = eq
            dd = ((peak - eq) / peak) * 100
            if dd > max_dd:
                max_dd = dd

        return {
            "symbol": clean_symbol,
            "timeframe": timeframe,
            "strategy": strategy,
            "initial_capital": initial_capital,
            "final_capital": round(capital, 2),
            "net_pnl_usd": net_pnl_usd,
            "net_pnl_pct": net_pnl_pct,
            "total_trades": total_trades,
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate_pct": win_rate,
            "profit_factor": profit_factor,
            "max_drawdown_pct": round(max_dd, 2),
            "fee_pct_per_side": fee_pct,
            "slippage_pct_per_side": slippage_pct,
            "equity_curve": equity_curve[-60:],  # last 60 points for chart
            "trades": trades[-25:]  # last 25 trades
        }
