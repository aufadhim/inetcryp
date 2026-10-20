import os
import uvicorn
from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
import pandas as pd
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
import secrets
import asyncio
from dotenv import load_dotenv

# Safe env loading (never prints credentials)
load_dotenv()

from engine.binance_client import BinanceClient
from engine.metrics import calculate_crypto_metrics, summarize_crypto_ticker
from engine.screener import CryptoScreener
from engine.backtester import CryptoBacktester
from engine.paper_trader import CryptoPaperTrader
from engine.telegram_bot import send_telegram_alert, format_whale_alert
from engine.ai_analyst import analyze_with_gemini
from engine.multi_exchange import CrossExchangeMarket
from engine.signal_engine import score_signal
from engine.promotion_gate import evaluate_promotion
from engine.compression_screener import CompressionScreener
from engine.numpang_paus_crypto import NumpangPausCrypto

app = FastAPI(title="INETCRYP - 24/7 Whale Tracker & Auto-Trading Terminal", version="1.0.0")


@app.get("/api/universe")
def universe_status():
    from engine.dynamic_universe import latest_snapshot
    return latest_snapshot()


@app.get("/api/research/status")
def research_status():
    import json
    from pathlib import Path
    path = Path("data/lab/status.json")
    if not path.exists():
        return {"status":"not_started"}
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
        stamp = datetime.fromisoformat(result["at"])
        result["age_seconds"] = max(0,(datetime.now(timezone.utc)-stamp).total_seconds())
        result["stale"] = result["age_seconds"] > 1800
        progress_path = Path("data/lab/progress.json")
        if result.get("phase") == "research" and progress_path.exists():
            result["progress"] = json.loads(progress_path.read_text(encoding="utf-8"))
        if Path("data/lab/registry.sqlite").exists():
            from engine.research_lab import Registry
            registry = Registry()
            try:
                advice = registry.get("advice", datetime.now(timezone.utc).date().isoformat())
                if advice:
                    result["adviser"] = advice
            finally:
                registry.db.close()
        return result
    except (OSError,ValueError,KeyError):
        return {"status":"unreadable"}

ALLOWED_ORIGINS = [x.strip() for x in os.getenv("ALLOWED_ORIGINS", "http://127.0.0.1:8090,http://localhost:8090").split(",") if x.strip()]
ACCESS_PASSWORD = os.getenv("ACCESS_PASSWORD", "").strip()
ALLOWED_TIMEFRAMES = {"1m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d"}
BACKTEST_SEMAPHORE = asyncio.Semaphore(1)


@app.middleware("http")
async def protect_api(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        if not ACCESS_PASSWORD:
            client_host = request.client.host if request.client else ""
            if client_host not in {"127.0.0.1", "::1", "localhost"}:
                return JSONResponse({"detail": "ACCESS_PASSWORD belum dikonfigurasi."}, status_code=503)
        else:
            supplied = request.headers.get("X-Access-Password", "")
            if not secrets.compare_digest(supplied, ACCESS_PASSWORD):
                return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return await call_next(request)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize engines
binance_client = BinanceClient()
screener_engine = CryptoScreener(binance_client)
backtester_engine = CryptoBacktester(binance_client)
paper_trader = CryptoPaperTrader(client=binance_client)
cross_exchange = CrossExchangeMarket()
compression_engine = CompressionScreener(binance_client)
paus_engine = NumpangPausCrypto(binance_client)

# Mount static files
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")
os.makedirs("data/reports", exist_ok=True)
app.mount("/reports", StaticFiles(directory="data/reports", html=True), name="reports")


@app.get("/")
async def serve_index():
    index_path = os.path.join("static", "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path, headers={"Cache-Control": "no-store"})
    return JSONResponse({"status": "running", "message": "INETCRYP Terminal Backend Active"})


@app.get("/api/tickers")
async def get_tickers(limit: int = Query(40, ge=1, le=100)):
    """Get list of active top USDT pairs."""
    tickers = binance_client.get_top_tickers(limit=limit)
    return {"status": "ok", "count": len(tickers), "data": tickers}


@app.get("/api/chart-data")
async def get_chart_data(
    symbol: str = Query("BTCUSDT", min_length=5, max_length=20),
    timeframe: str = Query("1h"),
    limit: int = Query(250, ge=20, le=1000)
):
    """Fetch candles and calculate full quantitative Bandarmology indicators."""
    timeframe = timeframe.lower()
    if timeframe not in ALLOWED_TIMEFRAMES:
        raise HTTPException(status_code=422, detail="Timeframe tidak didukung")
    df = binance_client.get_klines(symbol, interval=timeframe, limit=limit)
    if df.empty:
        raise HTTPException(status_code=404, detail=f"No candle data found for {symbol}")

    df_calc = calculate_crypto_metrics(df)

    # Format lightweight-charts candlesticks
    candles = []
    volumes = []
    lpm_series = []
    trigger_series = []
    bandar_cost_series = []

    for idx, row in df_calc.iterrows():
        # Timestamp in seconds for lightweight-charts
        t_sec = int(idx.timestamp())
        o = float(row["Open"])
        h = float(row["High"])
        l = float(row["Low"])
        c = float(row["Close"])
        v = float(row["Volume"])
        inten = float(row.get("Intensity", 1.0))
        is_up = c >= o

        # Purple spike for high intensity anomaly volume (> 2.0x)
        if inten >= 2.0:
            vol_color = "rgba(168, 85, 247, 0.85)"  # Purple Neon
        elif is_up:
            vol_color = "rgba(16, 185, 129, 0.5)"   # Green
        else:
            vol_color = "rgba(239, 68, 68, 0.5)"    # Red

        candles.append({"time": t_sec, "open": o, "high": h, "low": l, "close": c})
        volumes.append({"time": t_sec, "value": v, "color": vol_color})

        if "LPM_Score" in row and not pd.isna(row["LPM_Score"]):
            lpm_series.append({"time": t_sec, "value": float(row["LPM_Score"])})
        if "LPM_Trigger" in row and not pd.isna(row["LPM_Trigger"]):
            trigger_series.append({"time": t_sec, "value": float(row["LPM_Trigger"])})
        if "Bandar_Cost" in row and not pd.isna(row["Bandar_Cost"]):
            bandar_cost_series.append({"time": t_sec, "value": float(row["Bandar_Cost"])})

    # Extra market insights
    futures_info = binance_client.get_futures_sentiment(symbol)
    summary = summarize_crypto_ticker(symbol, df_calc, extra=futures_info)

    return {
        "status": "ok",
        "symbol": symbol.upper(),
        "timeframe": timeframe,
        "summary": summary,
        "candles": candles,
        "volumes": volumes,
        "lpm_score": lpm_series,
        "lpm_trigger": trigger_series,
        "bandar_cost": bandar_cost_series
    }


@app.get("/api/orderbook")
async def get_orderbook(symbol: str = Query("BTCUSDT", min_length=5, max_length=20)):
    """Fetch live orderbook depth & wall detection."""
    depth = binance_client.get_orderbook_depth(symbol)
    return {"status": "ok", "symbol": symbol.upper(), "data": depth}


@app.get("/api/cross-exchange")
async def get_cross_exchange(symbol: str = Query("BTCUSDT", min_length=5, max_length=20)):
    """Read-only orderbook pressure snapshot across major public exchanges."""
    return {"status": "ok", "data": cross_exchange.snapshot(symbol)}


@app.get("/api/signal")
async def get_signal(symbol: str = Query("BTCUSDT", min_length=5, max_length=20), timeframe: str = Query("1h")):
    if timeframe.lower() not in ALLOWED_TIMEFRAMES:
        raise HTTPException(status_code=422, detail="Timeframe tidak didukung")
    df = binance_client.get_klines(symbol, interval=timeframe.lower(), limit=120)
    if df.empty:
        raise HTTPException(status_code=404, detail="Data candle tidak tersedia")
    summary = summarize_crypto_ticker(symbol, calculate_crypto_metrics(df))
    cross = cross_exchange.snapshot(symbol)
    return {"status": "ok", "summary": summary, "cross_exchange": cross, "signal": score_signal(summary, cross)}


@app.get("/api/health")
async def get_health():
    """Non-secret process and storage health information."""
    import json
    status_path = os.path.join("data", "worker_status.json")
    worker = {"status": "not_seen"}
    if os.path.exists(status_path):
        try:
            with open(status_path, "r", encoding="utf-8") as handle:
                worker = json.load(handle)
        except (OSError, ValueError):
            worker = {"status": "unreadable"}
    heartbeat_age_seconds = None
    if worker.get("last_heartbeat"):
        try:
            stamp = datetime.fromisoformat(worker["last_heartbeat"])
            heartbeat_age_seconds = max(0, int((datetime.now(timezone.utc) - stamp).total_seconds()))
        except (TypeError, ValueError):
            worker = {**worker, "status": "unreadable_heartbeat"}
    worker_stale = heartbeat_age_seconds is None or heartbeat_age_seconds > 900
    if worker_stale and worker.get("status") == "running":
        worker = {**worker, "status": "stale"}
    return {
        "status": "degraded" if worker_stale else "ok",
        "api": "online",
        "paper_worker": worker,
        "worker_stale": worker_stale,
        "heartbeat_age_seconds": heartbeat_age_seconds,
        "read_only": True,
        "telegram_configured": bool(os.getenv("TELEGRAM_BOT_TOKEN", "").strip() and os.getenv("TELEGRAM_CHAT_ID", "").strip()),
        "gemini_configured": bool(os.getenv("GEMINI_API_KEY", "").strip()),
    }


@app.get("/api/promotion/status")
async def get_promotion_status():
    return {"status": "ok", "data": evaluate_promotion(paper_trader.get_summary(refresh=False))}


@app.get("/api/whale-prints")
async def get_whale_prints(symbol: str = Query("BTCUSDT", min_length=5, max_length=20), min_usdt: float = Query(10000.0, ge=1, le=10_000_000)):
    """Fetch real-time aggressive large orders (> $10,000 USDT)."""
    prints = binance_client.get_whale_prints(symbol, min_usdt=min_usdt)
    return {"status": "ok", "symbol": symbol.upper(), "count": len(prints), "data": prints}


@app.get("/api/screener")
async def run_screener_api(
    timeframe: str = Query("1h"),
    preset: str = Query("all", description="all, silent_acc, markup_breakout, whale_dominant, near_cost, distribution_warning"),
    limit: int = Query(30, ge=1, le=50)
):
    if timeframe.lower() not in ALLOWED_TIMEFRAMES:
        raise HTTPException(status_code=422, detail="Timeframe tidak didukung")
    """Screen top liquid crypto pairs with quantitative whale presets."""
    data = screener_engine.scan_all(timeframe=timeframe, limit_symbols=limit)
    filtered = screener_engine.filter_preset(data, preset) if preset != "all" else data
    return {
        "status": "ok",
        "timeframe": timeframe,
        "preset": preset,
        "count": len(filtered),
        "total_scanned": len(data),
        "data": filtered
    }


@app.get("/api/screener/compression")
async def compression_watchlist(
    timeframe: str = Query("4h"),
    limit: int = Query(50, ge=10, le=100)
):
    if timeframe.lower() not in ALLOWED_TIMEFRAMES:
        raise HTTPException(status_code=422, detail="Timeframe tidak didukung")
    from starlette.concurrency import run_in_threadpool
    data = await run_in_threadpool(compression_engine.scan, timeframe.lower(), limit)
    return {"status": "ok", "setup": "post_downtrend_compression_v1",
            "timeframe": timeframe.lower(), "count": len(data), "data": data}


@app.get("/api/paus/{symbol}")
async def numpang_paus_crypto(symbol: str, timeframe: str = Query("4h")):
    if timeframe.lower() not in ALLOWED_TIMEFRAMES:
        raise HTTPException(status_code=422, detail="Timeframe tidak didukung")
    from starlette.concurrency import run_in_threadpool
    return await run_in_threadpool(paus_engine.analyze, symbol.upper(), timeframe.lower())


@app.get("/api/narrative-radar")
async def narrative_radar_snapshot():
    import json
    path = "data/research/narrative-latest.json"
    if not os.path.exists(path):
        return {"status": "warming_up", "matches": []}
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        raise HTTPException(status_code=503, detail="Snapshot radar tidak valid")


@app.get("/api/backtest")
async def run_backtest_api(
    symbol: str = Query("BTCUSDT"),
    timeframe: str = Query("15m"),
    strategy: str = Query("ema_pullback_v1"),
    initial_capital: float = Query(1000.0, gt=0, le=10_000_000),
    tp: float = Query(3.0, gt=0, le=100),
    sl: float = Query(1.5, gt=0, le=100),
    bars: int = Query(400, ge=50, le=20000),
    fee_pct: float = Query(0.1, ge=0, le=5),
    slippage_pct: float = Query(0.05, ge=0, le=5)
):
    if timeframe.lower() not in ALLOWED_TIMEFRAMES:
        raise HTTPException(status_code=422, detail="Timeframe tidak didukung")
    """Run backtesting simulator."""
    from starlette.concurrency import run_in_threadpool
    if BACKTEST_SEMAPHORE.locked():
        raise HTTPException(status_code=429, detail="Backtest lain sedang berjalan")
    async with BACKTEST_SEMAPHORE:
        try:
            result = await asyncio.wait_for(run_in_threadpool(backtester_engine.run,
                symbol=symbol,
                timeframe=timeframe,
                strategy=strategy,
                initial_capital=initial_capital,
                tp_pct=tp,
                sl_pct=sl,
                limit_bars=bars,
                fee_pct=fee_pct,
                slippage_pct=slippage_pct
            ), timeout=120)
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="Backtest melewati batas waktu 120 detik")
    return {"status": "ok", "result": result}


@app.get("/api/paper-trading/status")
async def get_paper_trading_status():
    """Get live 24/7 paper trading portfolio summary."""
    return {"status": "ok", "data": paper_trader.get_summary()}


@app.post("/api/paper-trading/run")
async def trigger_paper_trading_cycle(timeframe: str = Query("15m")):
    """Trigger one manual forward testing / paper trade cycle."""
    if timeframe.lower() not in ALLOWED_TIMEFRAMES:
        raise HTTPException(status_code=422, detail="Timeframe tidak didukung")
    res = paper_trader.run_eval_cycle(timeframe=timeframe.lower())
    return {"status": "ok", "result": res}


@app.post("/api/paper-trading/reset")
async def reset_paper_trading(initial_balance: float = Query(1000.0, gt=0, le=10_000_000)):
    """Reset virtual paper trading portfolio."""
    res = paper_trader.reset_state(initial_balance=initial_balance)
    return {"status": "ok", "data": res}


@app.get("/api/ai-analyze")
async def ai_analyze(symbol: str = Query("BTCUSDT", min_length=5, max_length=20), timeframe: str = Query("1h")):
    """Get AI Reasoning for whale activity from Google Gemini."""
    if timeframe.lower() not in ALLOWED_TIMEFRAMES:
        raise HTTPException(status_code=422, detail="Timeframe tidak didukung")
    df = binance_client.get_klines(symbol, interval=timeframe.lower(), limit=80)
    if df.empty:
        raise HTTPException(status_code=404, detail="Candle data not available")

    df_calc = calculate_crypto_metrics(df)
    depth = binance_client.get_orderbook_depth(symbol)
    extra = {"bid_ask_ratio": depth.get("bid_ask_ratio", 1.0)}
    summary = summarize_crypto_ticker(symbol, df_calc, extra=extra)

    analysis_text = analyze_with_gemini(symbol, summary)
    return {"status": "ok", "symbol": symbol.upper(), "analysis": analysis_text}


@app.post("/api/telegram/test")
async def test_telegram_alert():
    """Send test alert to Telegram."""
    msg = """🐋 <b>INETCRYP — Test Alert Berhasil!</b>
━━━━━━━━━━━━━━━━━━
Koneksi Telegram Bot 24/7 telah aktif.
Notifikasi akumulasi paus & sinyal trading akan dikirim secara instan ke sini.
━━━━━━━━━━━━━━━━━━
⚡ <i>Status: Online & Siap Mengawal Pasar 24/7</i>"""
    success = send_telegram_alert(msg)
    if success:
        return {"status": "ok", "message": "Test alert terkirim ke Telegram!"}
    return {"status": "error", "message": "Gagal mengirim alert. Pastikan TELEGRAM_BOT_TOKEN dan TELEGRAM_CHAT_ID sudah benar."}


@app.get("/api/account/status")
async def get_account_status():
    """Check Binance API connectivity & balance securely."""
    bal = binance_client.get_account_balances()
    return {"status": "ok", "data": bal}


import socket

def is_port_in_use(p: int, h: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((h, p)) == 0


if __name__ == "__main__":
    configured_port = int(os.getenv("PORT", 8090))
    host = os.getenv("HOST", "127.0.0.1")
    port = configured_port
    if is_port_in_use(port, host):
        port = 8090 if port != 8090 else 8091
        print(f"[WARN] Port {configured_port} sedang digunakan (misal: NumpangPaus Saham). Mengalihkan INETCRYP ke port {port}.")
    print(f"[INETCRYP] Terminal running on http://{host}:{port}")
    uvicorn.run("server:app", host=host, port=port, reload=True)
