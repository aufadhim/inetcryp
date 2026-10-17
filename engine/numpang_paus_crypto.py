"""Explainable multi-layer whale-following score for liquid crypto markets."""
from __future__ import annotations
from typing import Any, Dict, Optional

from engine.binance_client import BinanceClient
from engine.compression_screener import analyze_compression
from engine.metrics import calculate_crypto_metrics
from engine.multi_exchange import CrossExchangeMarket


def score_layers(symbol: str, frame, orderbook: Dict[str, Any], futures: Dict[str, Any],
                 cross: Dict[str, Any]) -> Dict[str, Any]:
    metrics = calculate_crypto_metrics(frame.iloc[:-1])
    if metrics.empty:
        return {"symbol": symbol, "status": "NO_DATA", "score": 0, "layers": {}}
    last = metrics.iloc[-1]
    layers, score = {}, 0.0

    cvd_recent = float(metrics.CVD_Delta.tail(12).sum())
    spot = 18 if cvd_recent > 0 and float(last.LPM_Score) >= 52 else (8 if cvd_recent > 0 else 0)
    layers["spot_accumulation"] = {"score": spot, "max": 18, "cvd_12": round(cvd_recent, 2),
        "lpm": float(last.LPM_Score)}
    score += spot

    pressure = float(cross.get("weighted_pressure_pct", 0))
    coverage = int(cross.get("exchange_count", 0))
    cross_score = 14 if coverage >= 2 and pressure >= 12 else (7 if coverage >= 2 and pressure > 0 else 0)
    layers["cross_exchange"] = {"score": cross_score, "max": 14, "pressure_pct": pressure, "coverage": coverage}
    score += cross_score

    ratio = float(orderbook.get("bid_ask_ratio", 1) or 1)
    book_score = 10 if ratio >= 1.35 else (5 if ratio >= 1.1 else 0)
    layers["orderbook"] = {"score": book_score, "max": 10, "bid_ask_ratio": ratio,
        "warning": "walls may be spoofed"}
    score += book_score

    funding = float(futures.get("funding_rate_pct", 0))
    derivatives_score = 10 if -0.01 <= funding <= 0.03 else (4 if funding <= 0.06 else 0)
    layers["derivatives"] = {"score": derivatives_score, "max": 10, "funding_rate_pct": funding}
    score += derivatives_score

    compression = analyze_compression(symbol, frame)
    structure_score = 0
    if compression:
        structure_score = 22 if compression["status"] == "BREAKOUT_CONFIRMED" else 14
    layers["structure"] = {"score": structure_score, "max": 22,
        "setup": compression["status"] if compression else "NONE"}
    score += structure_score

    regime_score = 14 if last.Close > last.EMA21 > last.EMA50 else (6 if last.Close > last.EMA50 else 0)
    layers["regime"] = {"score": regime_score, "max": 14}
    score += regime_score

    liquidity_score = 12 if float(last.get("QuoteVolume", 0)) >= 1_000_000 else 5
    layers["liquidity"] = {"score": liquidity_score, "max": 12,
        "latest_quote_volume": round(float(last.get("QuoteVolume", 0)), 2)}
    score += liquidity_score

    label = "PAUS_CONFIRMED_WATCH" if score >= 72 else ("EARLY_WATCH" if score >= 55 else "NO_EDGE")
    contradictions = []
    if funding > 0.06: contradictions.append("funding terlalu panas")
    if pressure < -12 and coverage >= 2: contradictions.append("tekanan jual lintas exchange")
    if cvd_recent <= 0: contradictions.append("spot CVD belum mendukung")
    return {"symbol": symbol, "status": label, "score": round(score, 1), "layers": layers,
        "contradictions": contradictions, "action": "watchlist_only",
        "limitations": ["OTC and hidden liquidity are not visible", "orderbook walls can be cancelled"]}


class NumpangPausCrypto:
    def __init__(self, client: Optional[BinanceClient] = None):
        self.client = client or BinanceClient()
        self.cross = CrossExchangeMarket()

    def analyze(self, symbol: str, timeframe="4h"):
        frame = self.client.get_klines(symbol, timeframe, 180)
        if frame.empty:
            return {"symbol": symbol, "status": "NO_DATA", "score": 0}
        return score_layers(symbol, frame, self.client.get_orderbook_depth(symbol),
                            self.client.get_futures_sentiment(symbol), self.cross.snapshot(symbol))
