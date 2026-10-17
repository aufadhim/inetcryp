import concurrent.futures
import pandas as pd
from typing import List, Dict, Any, Optional
from engine.binance_client import BinanceClient
from engine.metrics import calculate_crypto_metrics, summarize_crypto_ticker


class CryptoScreener:
    def __init__(self, client: Optional[BinanceClient] = None):
        self.client = client or BinanceClient()

    def scan_all(self, timeframe: str = "1h", limit_symbols: int = 35) -> List[Dict[str, Any]]:
        """Scan top volume USDT pairs in parallel."""
        top_tickers = self.client.get_top_tickers(limit=limit_symbols)
        if not top_tickers:
            return []

        results = []

        def process_symbol(ticker_info: Dict[str, Any]):
            sym = ticker_info["symbol"]
            try:
                df = self.client.get_klines(sym, interval=timeframe, limit=120)
                if df.empty or len(df) < 20:
                    return None
                df_calc = calculate_crypto_metrics(df)
                summary = summarize_crypto_ticker(sym, df_calc, extra={
                    "high_24h": ticker_info.get("high_24h", 0.0),
                    "low_24h": ticker_info.get("low_24h", 0.0),
                    "trades_24h": ticker_info.get("trades_24h", 0)
                })
                return summary
            except Exception:
                return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            future_to_sym = {executor.submit(process_symbol, t): t for t in top_tickers}
            for future in concurrent.futures.as_completed(future_to_sym):
                res = future.result()
                if res and res.get("status") != "NO_DATA":
                    results.append(res)

        # Sort by 24h Volume
        results.sort(key=lambda x: x.get("volume_usdt", 0), reverse=True)
        return results

    def filter_preset(self, data: List[Dict[str, Any]], preset: str) -> List[Dict[str, Any]]:
        """Filter results based on Whale strategy presets."""
        preset = preset.lower()
        if preset == "silent_acc":
            # Nyerok Paus Murah: Bullish Divergence or LPM high in discount/fair zone
            return [x for x in data if x.get("divergence") == "BULLISH_DIVERGENCE" or (x.get("lpm_score", 0) >= 55 and x.get("dist_bandar_pct", 0) <= 2.5)]
        elif preset == "markup_breakout":
            # Siap Terbang: Phase Mark-Up & Intensity >= 1.8
            return [x for x in data if x.get("phase") == "MARK_UP" and x.get("intensity", 0) >= 1.8]
        elif preset == "whale_dominant":
            # Dominasi Paus: LPM Score >= 58
            return [x for x in data if x.get("lpm_score", 0) >= 58.0]
        elif preset == "near_cost":
            # Dekat Modal Bandar: -3.5% s/d +3.5%
            return [x for x in data if -3.5 <= x.get("dist_bandar_pct", 99) <= 3.5]
        elif preset == "distribution_warning":
            # Bahaya Cuci Piring: Bearish divergence or Phase Distribusi
            return [x for x in data if x.get("divergence") == "BEARISH_DIVERGENCE" or x.get("phase") == "DISTRIBUSI"]
        return data
