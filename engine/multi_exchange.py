"""Public, read-only cross-exchange market data.

This module deliberately uses public endpoints only. It never reads exchange
credentials and never places orders.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List
import requests


class CrossExchangeMarket:
    def __init__(self, timeout: float = 6.0):
        self.timeout = timeout

    def _get(self, url: str, params: Dict[str, Any]) -> Any:
        response = requests.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def _binance(self, symbol: str) -> Dict[str, Any]:
        data = self._get("https://api.binance.com/api/v3/depth", {"symbol": symbol, "limit": 50})
        bids, asks = data.get("bids", []), data.get("asks", [])
        return self._normalize("binance", symbol, bids, asks)

    def _bybit(self, symbol: str) -> Dict[str, Any]:
        data = self._get("https://api.bybit.com/v5/market/orderbook", {"category": "spot", "symbol": symbol, "limit": 50})
        result = data.get("result", {})
        return self._normalize("bybit", symbol, result.get("b", []), result.get("a", []))

    def _okx(self, symbol: str) -> Dict[str, Any]:
        inst_id = symbol[:-4] + "-USDT" if symbol.endswith("USDT") else symbol
        data = self._get("https://www.okx.com/api/v5/market/books", {"instId": inst_id, "sz": 50})
        books = data.get("data", [{}])[0]
        return self._normalize("okx", symbol, books.get("bids", []), books.get("asks", []))

    @staticmethod
    def _normalize(exchange: str, symbol: str, bids: List[Any], asks: List[Any]) -> Dict[str, Any]:
        def value(level: Any) -> float:
            try:
                return float(level[0]) * float(level[1])
            except (TypeError, ValueError, IndexError):
                return 0.0

        bid_value = sum(value(x) for x in bids)
        ask_value = sum(value(x) for x in asks)
        total = bid_value + ask_value
        pressure = ((bid_value - ask_value) / total * 100.0) if total else 0.0
        return {
            "exchange": exchange,
            "symbol": symbol,
            "bid_volume_usdt": round(bid_value, 2),
            "ask_volume_usdt": round(ask_value, 2),
            "pressure_pct": round(pressure, 2),
            "bid_ask_ratio": round(bid_value / ask_value, 3) if ask_value else None,
            "levels": len(bids) + len(asks),
            "status": "ok",
        }

    def snapshot(self, symbol: str = "BTCUSDT") -> Dict[str, Any]:
        symbol = symbol.upper().replace("/", "").replace("-", "")
        loaders = {"binance": self._binance, "bybit": self._bybit, "okx": self._okx}
        results: List[Dict[str, Any]] = []
        errors: List[Dict[str, str]] = []
        with ThreadPoolExecutor(max_workers=len(loaders)) as pool:
            futures = {pool.submit(loader, symbol): exchange for exchange, loader in loaders.items()}
            for future in as_completed(futures):
                exchange = futures[future]
                try:
                    results.append(future.result())
                except Exception as exc:
                    errors.append({"exchange": exchange, "error": str(exc)[:160]})

        weighted_total = sum(abs(row["bid_volume_usdt"] + row["ask_volume_usdt"]) for row in results)
        consensus = 0.0
        if weighted_total:
            consensus = sum(row["pressure_pct"] * (row["bid_volume_usdt"] + row["ask_volume_usdt"]) for row in results) / weighted_total
        return {
            "symbol": symbol,
            "exchanges": sorted(results, key=lambda row: row["exchange"]),
            "errors": errors,
            "exchange_count": len(results),
            "coverage_pct": round(len(results) / len(loaders) * 100, 1),
            "weighted_pressure_pct": round(consensus, 2),
            "interpretation": self._interpret(consensus, len(results)),
            "limitations": [
                "Snapshot orderbooks do not reveal OTC or hidden liquidity.",
                "Exchange volumes are not automatically comparable across quote currencies.",
                "A wall can be cancelled and may represent spoofing rather than genuine demand.",
            ],
        }

    @staticmethod
    def _interpret(pressure: float, count: int) -> str:
        if count < 2:
            return "LOW_COVERAGE"
        if pressure >= 15:
            return "CROSS_EXCHANGE_BUY_PRESSURE"
        if pressure <= -15:
            return "CROSS_EXCHANGE_SELL_PRESSURE"
        return "MIXED_OR_BALANCED"
