import os
import time
import hmac
import hashlib
import requests
import pandas as pd
from typing import Dict, Any, List, Optional
from urllib.parse import urlencode
from dotenv import load_dotenv

# Load env variables safely without printing/logging them
load_dotenv()

# Binance Host Endpoints
BINANCE_PUBLIC_HOSTS = [
    "https://api.binance.com",
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com",
    "https://data-api.binance.vision"
]

BINANCE_TESTNET_HOST = "https://testnet.binance.vision"
BINANCE_FUTURES_HOST = "https://fapi.binance.com"


class BinanceClient:
    def __init__(self):
        self.api_key = os.getenv("BINANCE_API_KEY", "").strip()
        self.api_secret = os.getenv("BINANCE_API_SECRET", "").strip()
        self.mode = os.getenv("BINANCE_MODE", "testnet").lower().strip()
        self.market_type = os.getenv("BINANCE_MARKET_TYPE", "spot").lower().strip()

        # Session with reasonable timeout and standard browser-like headers
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json"
        })
        if self.api_key:
            self.session.headers.update({"X-MBX-APIKEY": self.api_key})

    def _get_base_url(self, for_signed: bool = False) -> str:
        if self.mode == "testnet" and for_signed:
            return BINANCE_TESTNET_HOST
        return BINANCE_PUBLIC_HOSTS[0]

    def _request(self, method: str, path: str, params: Optional[Dict[str, Any]] = None, signed: bool = False) -> Optional[Any]:
        if params is None:
            params = {}

        if signed:
            if not self.api_key or not self.api_secret:
                return None
            params["timestamp"] = int(time.time() * 1000)
            query_string = urlencode(params)
            signature = hmac.new(
                self.api_secret.encode("utf-8"),
                query_string.encode("utf-8"),
                hashlib.sha256
            ).hexdigest()
            params["signature"] = signature

        # Host selection
        if signed and self.mode == "testnet":
            hosts = [BINANCE_TESTNET_HOST]
        elif signed:
            hosts = [host for host in BINANCE_PUBLIC_HOSTS if host != "https://data-api.binance.vision"]
        else:
            hosts = BINANCE_PUBLIC_HOSTS

        for attempt, host in enumerate(hosts):
            url = f"{host}{path}"
            try:
                resp = self.session.request(method, url, params=params, timeout=8)
                if resp.status_code == 200:
                    return resp.json()
                elif resp.status_code == 429:
                    time.sleep(min(2 ** attempt, 8))
                    continue
                else:
                    continue
            except Exception:
                continue
        return None

    def get_top_tickers(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Fetch 24hr ticker price change statistics for USDT pairs, sorted by volume."""
        data = self._request("GET", "/api/v3/ticker/24hr")
        if not data or not isinstance(data, list):
            return []

        # Filter strictly active USDT spot pairs
        usdt_pairs = []
        for item in data:
            symbol = item.get("symbol", "")
            if symbol.endswith("USDT") and not any(x in symbol for x in ["UPUSDT", "DOWNUSDT", "BEARUSDT", "BULLUSDT"]):
                try:
                    quote_vol = float(item.get("quoteVolume", 0.0))
                    price = float(item.get("lastPrice", 0.0))
                    price_change_pct = float(item.get("priceChangePercent", 0.0))
                    high = float(item.get("highPrice", 0.0))
                    low = float(item.get("lowPrice", 0.0))
                    trades = int(item.get("count", 0))

                    if quote_vol > 500000:  # Minimum 500k USDT volume
                        usdt_pairs.append({
                            "symbol": symbol,
                            "price": price,
                            "change_pct": round(price_change_pct, 2),
                            "high_24h": high,
                            "low_24h": low,
                            "volume_usdt": round(quote_vol, 2),
                            "trades_24h": trades
                        })
                except (ValueError, TypeError):
                    continue

        usdt_pairs.sort(key=lambda x: x["volume_usdt"], reverse=True)
        return usdt_pairs[:limit]

    def get_klines(self, symbol: str, interval: str = "1h", limit: int = 300) -> pd.DataFrame:
        """
        Fetch OHLCV klines with volume delta calculation.
        Intervals: 1m, 5m, 15m, 1h, 4h, 1d
        """
        clean_symbol = symbol.upper().replace("/", "").replace("-", "")
        params = {
            "symbol": clean_symbol,
            "interval": interval,
            "limit": limit
        }
        data = self._request("GET", "/api/v3/klines", params=params)
        if not data or not isinstance(data, list):
            return pd.DataFrame()

        # Binance Kline Schema:
        # [0] Open time, [1] Open, [2] High, [3] Low, [4] Close, [5] Volume,
        # [6] Close time, [7] Quote asset volume, [8] Number of trades,
        # [9] Taker buy base asset volume, [10] Taker buy quote asset volume, [11] Ignore
        records = []
        for row in data:
            try:
                open_time = pd.to_datetime(row[0], unit="ms")
                open_p = float(row[1])
                high_p = float(row[2])
                low_p = float(row[3])
                close_p = float(row[4])
                vol = float(row[5])
                quote_vol = float(row[7])
                trades = int(row[8])
                taker_buy_vol = float(row[9])
                taker_buy_quote = float(row[10])

                # Aggressive buyer vs seller volume
                taker_sell_vol = max(0.0, vol - taker_buy_vol)
                taker_sell_quote = max(0.0, quote_vol - taker_buy_quote)
                cvd_delta = taker_buy_quote - taker_sell_quote

                records.append({
                    "Date": open_time,
                    "Open": open_p,
                    "High": high_p,
                    "Low": low_p,
                    "Close": close_p,
                    "Volume": vol,
                    "QuoteVolume": quote_vol,
                    "Trades": trades,
                    "BuyVolume": taker_buy_vol,
                    "SellVolume": taker_sell_vol,
                    "BuyQuote": taker_buy_quote,
                    "SellQuote": taker_sell_quote,
                    "CVD_Delta": cvd_delta
                })
            except Exception:
                continue

        df = pd.DataFrame(records)
        if not df.empty:
            df.set_index("Date", inplace=True)
            df.sort_index(inplace=True)
        return df

    def get_orderbook_depth(self, symbol: str, limit: int = 50) -> Dict[str, Any]:
        """Fetch orderbook depth and calculate bid/ask wall ratio & pressure."""
        clean_symbol = symbol.upper().replace("/", "").replace("-", "")
        data = self._request("GET", "/api/v3/depth", params={"symbol": clean_symbol, "limit": limit})
        if not data or "bids" not in data or "asks" not in data:
            return {"bid_volume_usdt": 0, "ask_volume_usdt": 0, "bid_ask_ratio": 1.0, "whale_walls": []}

        bid_vol_usdt = sum(float(b[0]) * float(b[1]) for b in data["bids"])
        ask_vol_usdt = sum(float(a[0]) * float(a[1]) for a in data["asks"])
        total_vol = bid_vol_usdt + ask_vol_usdt
        ratio = round(bid_vol_usdt / ask_vol_usdt, 2) if ask_vol_usdt > 0 else 1.0

        # Detect orderbook whale walls (single price level > 15% of depth)
        walls = []
        for b in data["bids"]:
            val = float(b[0]) * float(b[1])
            if total_vol > 0 and (val / total_vol) >= 0.10:
                walls.append({"type": "BUY_WALL", "price": float(b[0]), "val_usdt": round(val, 2)})

        for a in data["asks"]:
            val = float(a[0]) * float(a[1])
            if total_vol > 0 and (val / total_vol) >= 0.10:
                walls.append({"type": "SELL_WALL", "price": float(a[0]), "val_usdt": round(val, 2)})

        return {
            "bid_volume_usdt": round(bid_vol_usdt, 2),
            "ask_volume_usdt": round(ask_vol_usdt, 2),
            "bid_pressure_pct": round((bid_vol_usdt / total_vol * 100), 1) if total_vol > 0 else 50.0,
            "bid_ask_ratio": ratio,
            "whale_walls": walls[:5]
        }

    def get_whale_prints(self, symbol: str, min_usdt: float = 30000.0, limit: int = 100) -> List[Dict[str, Any]]:
        """Fetch recent aggregated trades and filter out large whale trades."""
        clean_symbol = symbol.upper().replace("/", "").replace("-", "")
        data = self._request("GET", "/api/v3/aggTrades", params={"symbol": clean_symbol, "limit": limit})
        if not data or not isinstance(data, list):
            return []

        prints = []
        for trade in data:
            try:
                price = float(trade.get("p", 0))
                qty = float(trade.get("q", 0))
                val_usdt = price * qty
                is_buyer_maker = trade.get("m", False)  # true = sell order taker, false = buy order taker
                trade_time = pd.to_datetime(trade.get("T", 0), unit="ms").strftime("%H:%M:%S")

                if val_usdt >= min_usdt:
                    prints.append({
                        "time": trade_time,
                        "price": price,
                        "qty": round(qty, 4),
                        "val_usdt": round(val_usdt, 2),
                        "side": "SELL" if is_buyer_maker else "BUY"
                    })
            except Exception:
                continue

        # Return latest first
        prints.reverse()
        return prints[:20]

    def get_futures_sentiment(self, symbol: str) -> Dict[str, Any]:
        """Fetch funding rate & open interest from Binance Futures."""
        clean_symbol = symbol.upper().replace("/", "").replace("-", "")
        result = {
            "funding_rate_pct": 0.0,
            "next_funding_time": "",
            "open_interest_usdt": 0.0
        }
        try:
            # Funding rate
            resp = self.session.get(f"{BINANCE_FUTURES_HOST}/fapi/v1/premiumIndex", params={"symbol": clean_symbol}, timeout=5)
            if resp.status_code == 200:
                p_data = resp.json()
                if isinstance(p_data, dict):
                    fr = float(p_data.get("lastFundingRate", 0.0)) * 100.0
                    result["funding_rate_pct"] = round(fr, 4)
                    nft = p_data.get("nextFundingTime", 0)
                    if nft:
                        result["next_funding_time"] = pd.to_datetime(nft, unit="ms").strftime("%H:%M UTC")

            # Open interest
            resp_oi = self.session.get(f"{BINANCE_FUTURES_HOST}/fapi/v1/openInterest", params={"symbol": clean_symbol}, timeout=5)
            if resp_oi.status_code == 200:
                oi_data = resp_oi.json()
                if isinstance(oi_data, dict):
                    oi_qty = float(oi_data.get("openInterest", 0.0))
                    result["open_interest_coins"] = round(oi_qty, 2)
        except Exception:
            pass

        return result

    def get_account_commission(self, symbol: str, production_read_only: bool = False):
        import re
        if not re.fullmatch(r"[A-Z0-9]{3,20}",symbol):
            raise ValueError("Invalid commission symbol")
        client=self
        if production_read_only and self.mode=="testnet":
            # Local copy for this GET only; never mutate the trading client's mode.
            import copy
            client=copy.copy(self)
            client.mode="live"
        return client._request("GET", "/api/v3/account/commission", {"symbol":symbol,"recvWindow":5000}, signed=True)

    def get_account_balances(self) -> Dict[str, Any]:
        """Fetch account balance if API credentials are valid."""
        data = self._request("GET", "/api/v3/account", signed=True)
        if not data or "balances" not in data:
            return {"connected": False, "usdt": 0.0, "assets": []}

        assets = []
        usdt_free = 0.0
        for b in data.get("balances", []):
            try:
                free = float(b.get("free", 0))
                locked = float(b.get("locked", 0))
                total = free + locked
                asset = b.get("asset", "")
                if asset == "USDT":
                    usdt_free = total
                elif total > 0.0001:
                    assets.append({"asset": asset, "free": free, "locked": locked, "total": round(total, 4)})
            except Exception:
                continue

        return {
            "connected": True,
            "mode": self.mode,
            "usdt": round(usdt_free, 2),
            "assets": assets[:10]
        }
