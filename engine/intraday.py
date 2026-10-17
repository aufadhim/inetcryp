"""Versioned long-only research rules. Input must contain closed candles only."""
import math

STRATEGY = "ema_pullback_v1"


def market_regime(frame):
    """Classify only from completed candles; ambiguous conditions must not trade."""
    if len(frame) < 100:
        return "INSUFFICIENT_DATA"
    now = frame.iloc[-1]
    required = ("Close", "EMA21", "EMA50", "ATR_PCT", "ADX14")
    if not all(k in frame.columns and math.isfinite(float(now[k])) for k in required):
        return "UNKNOWN"
    if float(now.ATR_PCT) >= 4.0:
        return "EXTREME_VOLATILITY"
    if float(now.ADX14) < 18:
        return "RANGE"
    if now.Close > now.EMA21 > now.EMA50:
        return "UPTREND"
    if now.Close < now.EMA21 < now.EMA50:
        return "DOWNTREND"
    return "TRANSITION"

def entry_signal(frame):
    if len(frame) < 100:
        return None
    now, prev = frame.iloc[-1], frame.iloc[-2]
    fields = ["Close", "Low", "EMA9", "EMA21", "EMA50", "ATR14", "RSI14", "RelativeVolume"]
    if not all(math.isfinite(float(now[k])) for k in fields):
        return None
    atr = float(now.ATR14)
    trend = now.EMA9 > now.EMA21 > now.EMA50 and now.EMA50 > prev.EMA50
    reclaim = prev.Low <= prev.EMA9 and now.Close > now.EMA9 and now.Close > prev.Close
    regime = market_regime(frame) if "ADX14" in frame.columns else "UPTREND"
    if (regime == "UPTREND" and trend and reclaim and atr > 0 and 45 <= now.RSI14 <= 68
            and now.RelativeVolume >= 1.15 and 0 < now.Close - now.EMA21 <= 1.5 * atr):
        return STRATEGY
    return None
