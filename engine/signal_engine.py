"""Transparent, explainable crypto signal scoring."""
from typing import Any, Dict


def score_signal(summary: Dict[str, Any], cross_exchange: Dict[str, Any] | None = None) -> Dict[str, Any]:
    score = 50.0
    reasons = []
    lpm = float(summary.get("lpm_score", 50.0))
    intensity = float(summary.get("intensity", 1.0))
    dist = float(summary.get("dist_bandar_pct", 0.0))
    phase = summary.get("phase", "")
    divergence = summary.get("divergence", "")
    if lpm >= 58:
        score += 15; reasons.append("LPM dominan")
    elif lpm <= 42:
        score -= 15; reasons.append("LPM lemah")
    if divergence == "BULLISH_DIVERGENCE":
        score += 15; reasons.append("bullish divergence")
    elif divergence == "BEARISH_DIVERGENCE":
        score -= 15; reasons.append("bearish divergence")
    if phase == "MARK_UP" and intensity >= 1.8:
        score += 10; reasons.append("volume mark-up")
    if dist > 8:
        score -= 10; reasons.append("jauh di atas modal paus")
    elif dist < -5:
        score += 5; reasons.append("deep discount")
    pressure = float((cross_exchange or {}).get("weighted_pressure_pct", 0.0))
    coverage = int((cross_exchange or {}).get("exchange_count", 0))
    if coverage >= 2:
        if pressure >= 15:
            score += 10; reasons.append("tekanan beli lintas exchange")
        elif pressure <= -15:
            score -= 10; reasons.append("tekanan jual lintas exchange")
    score = round(max(0.0, min(100.0, score)), 1)
    if score >= 70:
        label = "BULLISH_SETUP"
    elif score <= 30:
        label = "BEARISH_RISK"
    else:
        label = "NEUTRAL_WAIT"
    confidence = round(min(95.0, 35.0 + coverage * 15.0 + min(len(reasons), 4) * 5.0), 1)
    return {"score": score, "label": label, "confidence_pct": confidence, "reasons": reasons, "coverage": coverage}
