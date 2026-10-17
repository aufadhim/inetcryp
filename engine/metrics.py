import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional


def classify_valuation_zone(dist_pct: float) -> str:
    """Classify price distance to Whale Cost / VWAP into valuation zones."""
    if pd.isna(dist_pct):
        return "Fair Value"
    if dist_pct <= -5.0:
        return "Deep Discount"
    elif dist_pct <= -1.5:
        return "Discount"
    elif dist_pct <= 3.0:
        return "Fair Value"
    elif dist_pct <= 8.0:
        return "Premium"
    else:
        return "Deep Premium"


def calculate_crypto_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate full suite of Crypto Quantitative Bandarmology indicators:
    - CLV (Close Location Value) [-1.0 to +1.0]
    - CVD (Cumulative Volume Delta - Aggressive Buyer vs Seller)
    - LPM (Likely Participant Movement) & LPM Score (0 - 100)
    - Slipstream Trigger Line (EMA-9 of LPM Score) & Crossover Signals
    - Volume Intensity Meter (Purple Spikes > 2.0x average)
    - Whale Cost Basis (VWAP of Accumulation Zone)
    - 4 Wyckoff Phases (AKUMULASI, MARK_UP, DISTRIBUSI, MARK_DOWN)
    - Bullish & Bearish Divergence Detection
    - Valuation Zones
    """
    if df.empty or len(df) < 15:
        return df

    res = df.copy()

    # 1. Close Location Value (CLV)
    high_low_diff = (res["High"] - res["Low"]).replace(0, np.nan)
    res["CLV"] = (((res["Close"] - res["Low"]) - (res["High"] - res["Close"])) / high_low_diff).fillna(0.0)

    # 2. Cumulative Volume Delta (CVD)
    if "CVD_Delta" in res.columns:
        res["CVD_Cum"] = res["CVD_Delta"].cumsum()
        res["CVD_SMA14"] = res["CVD_Cum"].rolling(14).mean()
    else:
        res["CVD_Delta"] = res["CLV"] * res["Volume"]
        res["CVD_Cum"] = res["CVD_Delta"].cumsum()
        res["CVD_SMA14"] = res["CVD_Cum"].rolling(14).mean()

    # 3. LPM (Likely Participant Movement)
    # Combined with Quote Volume and CVD Delta for crypto precision
    res["MoneyFlow"] = res["CLV"] * res["QuoteVolume"] if "QuoteVolume" in res.columns else res["CLV"] * res["Volume"] * res["Close"]
    res["LPM_Cum"] = res["MoneyFlow"].cumsum()
    res["LPM_SMA10"] = res["LPM_Cum"].rolling(10).mean()
    res["LPM_SMA30"] = res["LPM_Cum"].rolling(30).mean()

    # 20-period Money Flow Ratio [-1.0, 1.0]
    roll_mf_20 = res["MoneyFlow"].rolling(20).sum()
    roll_val_20 = res["QuoteVolume"].rolling(20).sum() if "QuoteVolume" in res.columns else (res["Volume"] * res["Close"]).rolling(20).sum()
    mfr_20 = (roll_mf_20 / roll_val_20.replace(0, np.nan)).fillna(0.0).clip(-1.0, 1.0)

    # 0 - 100 LPM Score
    res["LPM_Score"] = ((mfr_20 * 50) + 50).clip(0, 100).round(1)
    res["LPM_Trigger"] = res["LPM_Score"].ewm(span=9, adjust=False).mean().round(1)

    # Slipstream Crossover
    prev_lpm = res["LPM_Score"].shift(1)
    prev_trig = res["LPM_Trigger"].shift(1)
    slipstream = []
    for i in range(len(res)):
        sc = res["LPM_Score"].iloc[i]
        tr = res["LPM_Trigger"].iloc[i]
        psc = prev_lpm.iloc[i]
        ptr = prev_trig.iloc[i]
        if pd.isna(sc) or pd.isna(tr) or pd.isna(psc) or pd.isna(ptr):
            slipstream.append("NONE")
        elif sc > tr and psc <= ptr and sc >= 45:
            slipstream.append("SLIPSTREAM_BULL")
        elif sc < tr and psc >= ptr and sc <= 55:
            slipstream.append("SLIPSTREAM_BEAR")
        elif sc > tr + 2.0 and sc >= 55:
            slipstream.append("ABOVE_TRIGGER")
        else:
            slipstream.append("NONE")
    res["Slipstream"] = slipstream

    # 4. Volume Intensity Meter
    res["Vol_SMA20"] = res["Volume"].rolling(20).mean()
    res["Intensity"] = (res["Volume"] / res["Vol_SMA20"].replace(0, np.nan)).fillna(1.0).round(2)
    res["Is_Spike"] = res["Intensity"] >= 2.0

    # 5. Moving Averages
    res["SMA20"] = res["Close"].rolling(20).mean()
    res["SMA50"] = res["Close"].rolling(50).mean()
    for span in (9, 21, 50):
        res[f"EMA{span}"] = res["Close"].ewm(span=span, adjust=False, min_periods=span).mean()
    true_range = pd.concat([res["High"] - res["Low"],
        (res["High"] - res["Close"].shift()).abs(),
        (res["Low"] - res["Close"].shift()).abs()], axis=1).max(axis=1)
    res["ATR14"] = true_range.rolling(14).mean()
    up_move = res["High"].diff()
    down_move = -res["Low"].diff()
    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=res.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=res.index)
    atr_sum = true_range.rolling(14).sum().replace(0, np.nan)
    plus_di = 100 * plus_dm.rolling(14).sum() / atr_sum
    minus_di = 100 * minus_dm.rolling(14).sum() / atr_sum
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    res["ADX14"] = dx.rolling(14).mean()
    res["ATR_PCT"] = (res["ATR14"] / res["Close"].replace(0, np.nan)) * 100
    res["RelativeVolume"] = res["Volume"] / res["Volume"].shift().rolling(20).mean().replace(0, np.nan)
    delta = res["Close"].diff()
    gains = delta.clip(lower=0).rolling(14).mean()
    losses = (-delta.clip(upper=0)).rolling(14).mean().replace(0, np.nan)
    res["RSI14"] = (100 - (100 / (1 + gains / losses))).fillna(50.0)
    res.loc[(losses.isna()) & (gains > 0), "RSI14"] = 100.0
    rolling_std = res["Close"].rolling(20).std()
    res["BB_MID20"] = res["SMA20"]
    res["BB_UPPER20"] = res["SMA20"] + (2 * rolling_std)
    res["BB_LOWER20"] = res["SMA20"] - (2 * rolling_std)
    res["HIGH20_PREV"] = res["High"].shift(1).rolling(20).max()

    # 6. Whale Cost Basis (VWAP of Accumulation Zone)
    # Accumulation bars: CLV > 0 and (Intensity > 1.2 or CVD > 0)
    acc_condition = (res["CLV"] > 0) & ((res["Intensity"] >= 1.2) | (res["CVD_Delta"] > 0))
    res["Acc_Volume"] = np.where(acc_condition, res["Volume"], 0.0)
    res["Acc_Val"] = np.where(acc_condition, res["Volume"] * res["Close"], 0.0)

    roll_acc_val = pd.Series(res["Acc_Val"], index=res.index).rolling(30).sum()
    roll_acc_vol = pd.Series(res["Acc_Volume"], index=res.index).rolling(30).sum()
    whale_cost = (roll_acc_val / roll_acc_vol.replace(0, np.nan))
    # Fallback to rolling typical price VWAP if no accumulation bars
    typical_p = (res["High"] + res["Low"] + res["Close"]) / 3.0
    fallback_vwap = (typical_p * res["Volume"]).rolling(30).sum() / res["Volume"].rolling(30).sum().replace(0, np.nan)
    res["Bandar_Cost"] = whale_cost.fillna(fallback_vwap).fillna(res["Close"]).round(4)
    res["Dist_Bandar_Pct"] = (((res["Close"] - res["Bandar_Cost"]) / res["Bandar_Cost"]) * 100).round(2)
    res["Valuation_Zone"] = res["Dist_Bandar_Pct"].apply(classify_valuation_zone)

    # 7. Wyckoff 4-Phase Classification
    phases = []
    divergences = []
    for i in range(len(res)):
        if i < 15:
            phases.append("AKUMULASI")
            divergences.append("NONE")
            continue

        c = res["Close"].iloc[i]
        sma20 = res["SMA20"].iloc[i]
        lpm = res["LPM_Score"].iloc[i]
        inten = res["Intensity"].iloc[i]
        dist = res["Dist_Bandar_Pct"].iloc[i]
        c_14 = res["Close"].iloc[i - 14]
        lpm_14 = res["LPM_Score"].iloc[i - 14]
        cvd_14 = res["CVD_Cum"].iloc[i - 14]
        cvd_curr = res["CVD_Cum"].iloc[i]

        price_chg_14 = ((c - c_14) / c_14) * 100
        lpm_chg_14 = lpm - lpm_14
        cvd_chg_14 = cvd_curr - cvd_14

        # Divergence Check
        div = "NONE"
        if price_chg_14 <= 0.5 and (lpm_chg_14 >= 10.0 or cvd_chg_14 > 0):
            div = "BULLISH_DIVERGENCE"  # Silent Whale Accumulation
        elif price_chg_14 >= 3.0 and (lpm_chg_14 <= -10.0 or cvd_chg_14 < 0):
            div = "BEARISH_DIVERGENCE"  # Whale Distribution / Retail Trap
        divergences.append(div)

        # Wyckoff Phase
        if lpm >= 55 and (c > sma20 or inten >= 1.8):
            phases.append("MARK_UP")
        elif lpm <= 42 and (c < sma20 or div == "BEARISH_DIVERGENCE"):
            if dist > 5.0 or div == "BEARISH_DIVERGENCE":
                phases.append("DISTRIBUSI")
            else:
                phases.append("MARK_DOWN")
        elif lpm >= 48 or div == "BULLISH_DIVERGENCE":
            phases.append("AKUMULASI")
        else:
            phases.append("MARK_DOWN")

    res["Phase"] = phases
    res["Divergence"] = divergences

    return res


def summarize_crypto_ticker(symbol: str, df: pd.DataFrame, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Generate concise status summary for dashboard cards and screeners."""
    if df.empty:
        return {"symbol": symbol, "status": "NO_DATA"}

    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else last

    change_pct = round(((last["Close"] - prev["Close"]) / prev["Close"]) * 100, 2)
    lpm = float(last.get("LPM_Score", 50.0))
    phase = str(last.get("Phase", "AKUMULASI"))
    div = str(last.get("Divergence", "NONE"))
    slip = str(last.get("Slipstream", "NONE"))
    intensity = float(last.get("Intensity", 1.0))
    bandar_cost = float(last.get("Bandar_Cost", last["Close"]))
    dist_pct = float(last.get("Dist_Bandar_Pct", 0.0))
    val_zone = str(last.get("Valuation_Zone", "Fair Value"))

    # Smart badge / recommendation
    if div == "BULLISH_DIVERGENCE" or (slip == "SLIPSTREAM_BULL" and dist_pct <= 2.0):
        action = "🐋 NYEROK PAUS"
        badge_color = "success"
    elif phase == "MARK_UP" and intensity >= 1.8:
        action = "🚀 MARK-UP BREAKOUT"
        badge_color = "primary"
    elif div == "BEARISH_DIVERGENCE" or (phase == "DISTRIBUSI" and dist_pct > 5.0):
        action = "⚠️ CUCI PIRING / DISTRIBUSI"
        badge_color = "danger"
    elif dist_pct <= -2.0 and lpm >= 50:
        action = "🎯 DISCOUNT ZONE"
        badge_color = "info"
    else:
        action = "HOLD / NETRAL"
        badge_color = "secondary"

    res = {
        "symbol": symbol,
        "price": float(last["Close"]),
        "change_pct": change_pct,
        "volume_usdt": float(last.get("QuoteVolume", 0.0)),
        "lpm_score": lpm,
        "phase": phase,
        "divergence": div,
        "slipstream": slip,
        "intensity": intensity,
        "bandar_cost": bandar_cost,
        "dist_bandar_pct": dist_pct,
        "valuation_zone": val_zone,
        "action_signal": action,
        "badge_color": badge_color
    }

    if extra:
        res.update(extra)

    return res
