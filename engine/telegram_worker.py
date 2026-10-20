"""Read-only Telegram crypto assistant for INETCRYP."""
import html
import os
import time
import requests
import json
import re
from typing import Any, Dict
from engine.ai_analyst import analyze_with_gemini
from engine.ai_chat import chat_with_gemini, is_failure
from engine.binance_client import BinanceClient
from engine.metrics import calculate_crypto_metrics, summarize_crypto_ticker
from engine.paper_trader import CryptoPaperTrader
from engine.signal_engine import score_signal
from engine.promotion_gate import evaluate_promotion
from engine.report_url import get_report_url

MENU = {"keyboard": [[{"text": "📒 Portfolio"}, {"text": "🔎 Screener"}], [{"text": "🐋 Paus BTCUSDT"}, {"text": "🧠 Narrative Radar"}], [{"text": "🗜️ Compression"}, {"text": "📈 Signal BTCUSDT"}], [{"text": "🤖 Analisa AI"}, {"text": "📊 Report"}], [{"text": "❓ Help"}]], "resize_keyboard": True, "is_persistent": True}


class TelegramWorker:
    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        self.allowed_chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
        self.base = f"https://api.telegram.org/bot{self.token}"
        self.client = BinanceClient()
        self.paper = CryptoPaperTrader(client=self.client)
        self.offset = 0
        self.conversation = []

    def portfolio_summary(self):
        # Read the worker's latest journal, never stale Telegram startup state.
        with open(self.paper.data_file, encoding="utf-8") as handle:
            state = json.load(handle)
        if not {"initial_balance", "cash_usdt", "open_positions", "history"} <= state.keys():
            raise ValueError("Incomplete paper snapshot")
        self.paper.state = state
        return self.paper.get_summary(refresh=True)

    def _call(self, method: str, params: Dict[str, Any] | None = None) -> Any:
        response = requests.get(f"{self.base}/{method}", params=params or {}, timeout=35)
        response.raise_for_status()
        return response.json().get("result", [])

    def send(self, chat_id: str, text: str, keyboard: bool = False) -> None:
        if not self.allowed_chat or str(chat_id) != self.allowed_chat:
            return
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        if keyboard:
            payload["reply_markup"] = MENU
        response = requests.post(f"{self.base}/sendMessage", json=payload, timeout=15)
        response.raise_for_status()

    def send_portfolio(self, chat_id: str) -> None:
        try:
            s = self.portfolio_summary()
        except Exception:
            self.send(chat_id, "Data paper terbaru belum bisa dibaca. Saya tidak akan menampilkan saldo lama sebagai saldo terkini.", keyboard=True)
            return
        lines = ["📒 <b>Portfolio Mark-to-Market</b>", f"Equity: <b>${s['equity']:,.2f}</b>", f"Cash: ${s['cash_usdt']:,.2f}", f"Open value: ${s['equity'] - s['cash_usdt']:,.2f}", f"Realized PnL: {s['realized_pnl_usd']:+.2f} USDT", f"Unrealized PnL: {s['unrealized_pnl_usd']:+.2f} USDT", f"Total PnL: {s['net_pnl_usd']:+.2f} USDT ({s['net_return_pct']:+.2f}%)", f"Open: {s['open_positions_count']}"]
        for symbol, pos in s["open_positions"].items():
            lines.append(f"\n{symbol}: {pos['pnl_pct']:+.2f}% (${pos['pnl_usd']:+.2f}) | mark ${pos['mark_price']:,.6f}")
        self.send(chat_id, "\n".join(lines), keyboard=True)

    def market_context(self, symbol: str) -> Dict[str, Any]:
        frame = self.client.get_klines(symbol, "1h", 80)
        market = {}
        if not frame.empty:
            market = summarize_crypto_ticker(symbol, calculate_crypto_metrics(frame))
            market["signal"] = score_signal(market)
        try:
            portfolio = self.portfolio_summary()
        except Exception:
            portfolio = {"status": "unavailable"}
        # Keep context useful but bounded. Never include API keys, Telegram IDs, or environment values.
        paper = {k: portfolio.get(k) for k in ("equity", "cash_usdt", "net_pnl_usd",
            "realized_pnl_usd", "unrealized_pnl_usd", "net_return_pct",
            "open_positions_count", "closed_trades_count", "win_rate_pct", "last_scan_time")}
        paper["open_positions"] = portfolio.get("open_positions", {})
        paper["recent_closed_trades"] = portfolio.get("history", [])[-5:]
        try:
            account = self.client.get_account_balances()
            binance = {"connected": bool(account.get("connected")), "mode": account.get("mode"),
                "usdt": account.get("usdt", 0), "assets": account.get("assets", [])[:10]}
        except Exception:
            binance = {"connected": False, "status": "unavailable"}
        try:
            from engine.dynamic_universe import latest_snapshot
            snapshot = latest_snapshot()
            screener = {"as_of": snapshot.get("as_of"), "stale": snapshot.get("stale"),
                        "symbols": snapshot.get("symbols", [])}
        except Exception:
            screener = {"status": "unavailable"}
        return {"requested_symbol": symbol, "market": market, "paper_portfolio": paper,
                "binance_read_only": binance, "dynamic_screener": screener,
                "data_scope": "No credentials or environment values included"}

    def handle(self, message: Dict[str, Any]) -> None:
        chat_id = str(message.get("chat", {}).get("id", ""))
        text = str(message.get("text", "")).strip()
        if not self.allowed_chat or chat_id != self.allowed_chat or not text:
            return
        parts = text.split()
        command = parts[0].split("@")[0].lower()
        explicit = re.search(r"\b([A-Z0-9]{2,15})/?USDT\b", text.upper())
        bare = re.search(r"\b(BTC|ETH|SOL|BNB|DOGE|PEPE|AVAX)\b", text.upper())
        symbol = explicit.group(1)+"USDT" if explicit else (bare.group(1)+"USDT" if bare else "BTCUSDT")
        normalized = text.lower().strip().rstrip("?!.")
        if command == "/start":
            self.send(chat_id, "🐋 <b>INETCRYP Crypto Assistant aktif.</b>\nMode: <b>Active Paper</b>\nSaya bisa membaca portfolio, market, screener, signal, report, dan berdiskusi dengan Gemini.", keyboard=True)
        elif command == "/help" or normalized in {"❓ help", "help"}:
            self.send(chat_id, "<b>INETCRYP Commands</b>\n/paper atau update porto\n/promotion\n/signal BTCUSDT\n/paus BTCUSDT\n/radar\n/ai BTCUSDT\n/screener\n/compression\n/report\nChat bebas: <i>bagaimana posisi saya?</i>", keyboard=True)
        elif command in {"/paper", "/portfolio", "/porto", "/update"} or normalized in {"update porto", "update portfolio", "portofolio", "portfolio", "porto", "📒 portfolio"}:
            self.send_portfolio(chat_id)
        elif command == "/signal" or normalized.startswith("📈 signal"):
            frame = self.client.get_klines(symbol, "1h", 80)
            if frame.empty:
                self.send(chat_id, f"Data {symbol} tidak tersedia.")
                return
            summary = summarize_crypto_ticker(symbol, calculate_crypto_metrics(frame))
            signal = score_signal(summary)
            self.send(chat_id, f"🐋 <b>{symbol}</b>\nHarga: <code>${summary['price']:,.4f}</code>\nLPM: <b>{summary['lpm_score']}</b>\nFase: {summary['phase']}\nSinyal: <b>{signal['label']}</b> ({signal['score']}/100)\nConfidence: {signal['confidence_pct']}%\nAlasan: {', '.join(signal['reasons']) or 'netral'}")
        elif command in {"/ai", "/gemini", "/analisa"} or normalized in {"🤖 analisa ai", "analisa ai"} or normalized.startswith(("analisa ", "analysis ", "analisis ")):
            frame = self.client.get_klines(symbol, "1h", 80)
            if frame.empty:
                self.send(chat_id, f"Data {symbol} tidak tersedia.")
                return
            summary = summarize_crypto_ticker(symbol, calculate_crypto_metrics(frame))
            answer = analyze_with_gemini(symbol, summary)
            self.send(chat_id, f"🤖 <b>Gemini — {symbol}</b>\n\n{html.escape(answer)}", keyboard=True)
        elif command == "/screener" or normalized in {"🔎 screener", "screener"}:
            from engine.dynamic_universe import latest_snapshot
            snapshot = latest_snapshot()
            if snapshot["stale"] or snapshot["status"] != "ok":
                self.send(chat_id, "🔎 Screener belum tersedia atau datanya kedaluwarsa. Entry baru tidak memakai snapshot lama.", keyboard=True)
            else:
                rows = [f"{html.escape(r['symbol'])}: 24h {r['change_24h_pct']:+.2f}% | spread {r['spread_pct']:.3f}%" for r in snapshot["candidates"]]
                self.send(chat_id, "🔎 <b>Dynamic Spot Screener</b>\n" + "\n".join(rows or ["Belum ada koin lolos filter."]) + "\nPantauan, bukan sinyal beli. Tetap menunggu entry EMA paper.", keyboard=True)
        elif command in {"/compression", "/watchlist"} or normalized in {"🗜️ compression", "compression", "watchlist"}:
            from engine.compression_screener import CompressionScreener
            rows = CompressionScreener(self.client).scan(timeframe="4h", limit_symbols=50)[:12]
            if not rows:
                self.send(chat_id, "🗜️ Belum ada setup post-downtrend compression yang lolos filter 4H.", keyboard=True)
            else:
                lines = ["🗜️ <b>Compression Watchlist — 4H</b>"]
                for row in rows:
                    icon = "✅" if row["status"] == "BREAKOUT_CONFIRMED" else ("⚠️" if row["status"] == "BREAKDOWN" else "👀")
                    lines.append(f"{icon} <b>{html.escape(row['symbol'])}</b> {row['score']:.0f}/100 | edge {row['distance_to_breakout_pct']:+.2f}% | RVOL {row['relative_volume']:.2f}x | CVD {'+' if row['cvd_accumulation'] else '-'}")
                lines.append("\nWatchlist saja; paper entry tetap dikarantina. Tunggu close breakout + volume + retest.")
                self.send(chat_id, "\n".join(lines), keyboard=True)
        elif command == "/paus" or normalized.startswith("🐋 paus"):
            from engine.numpang_paus_crypto import NumpangPausCrypto
            result = NumpangPausCrypto(self.client).analyze(symbol)
            layers = result.get("layers", {})
            lines = [f"🐋 <b>NumpangPaus Crypto — {html.escape(symbol)}</b>",
                f"Status: <b>{result.get('status')}</b>", f"Score: <b>{result.get('score', 0)}/100</b>"]
            for name, layer in layers.items():
                lines.append(f"• {html.escape(name)}: {layer.get('score', 0)}/{layer.get('max', 0)}")
            if result.get("contradictions"):
                lines.append("Kontradiksi: "+html.escape(", ".join(result["contradictions"])))
            lines.append("Watchlist saja; bukan perintah beli.")
            self.send(chat_id, "\n".join(lines), keyboard=True)
        elif command == "/radar" or normalized in {"🧠 narrative radar", "narrative radar", "radar"}:
            try:
                with open("data/research/narrative-latest.json", encoding="utf-8") as handle:
                    radar = json.load(handle)
            except Exception:
                self.send(chat_id, "🧠 Narrative Radar belum memiliki snapshot yang valid.", keyboard=True)
                return
            candidates = []
            for narrative in radar.get("matches", []):
                for token in narrative.get("token_candidates", [])[:2]:
                    candidates.append((narrative, token))
            candidates.sort(key=lambda item: -item[1].get("score", 0))
            lines = ["🧠 <b>Narrative-to-Token Radar</b>"]
            for narrative, token in candidates[:10]:
                lines.append(f"• <b>{html.escape(str(token.get('symbol') or '?'))}</b> {token.get('score',0):.0f}/100 | {html.escape(str(narrative.get('name') or narrative.get('title')))} | LP ${token.get('liquidity_usd',0):,.0f}")
            lines.append("\nAfiliasi proyek belum terverifikasi. Alert only; jangan auto-buy.")
            self.send(chat_id, "\n".join(lines if len(lines)>2 else lines+["Belum ada kecocokan yang lolos."]), keyboard=True)
        elif command in {"/research", "/learning", "/lab"}:
            try:
                with open("data/lab/status.json", encoding="utf-8") as handle:
                    lab = json.load(handle)
                research = lab.get("research", {})
                tournament = lab.get("tournament", {})
                lines = ["🧪 <b>INETCRYP Research Lab</b>",
                    "Worker: "+html.escape(str(lab.get("status"))),
                    "Waktu: "+html.escape(str(lab.get("at"))),
                    "Eksperimen: "+html.escape(str(research.get("status", "berjalan"))),
                    "Lolos: "+str(research.get("gate", {}).get("eligible", "menunggu")),
                    "Champion paper: "+html.escape(str(tournament.get("champion") or "belum ada"))]
                for row in tournament.get("accounts", []):
                    lines.append(html.escape(f"{row['family']}: ${row['equity']:.2f}, {row['trades']} trades, PF {row['profit_factor']:.2f}"))
                lines.extend(html.escape(reason) for reason in research.get("gate", {}).get("reasons", []))
                self.send(chat_id, "\n".join(lines), keyboard=True)
            except (OSError, ValueError, KeyError):
                self.send(chat_id, "Research Lab sedang menyiapkan data awal.", keyboard=True)
        elif command == "/report" or normalized in {"📊 report", "report"}:
            url = get_report_url()
            self.send(chat_id, f"📊 <b>Report terbaru</b>\n<a href=\"{html.escape(url, quote=True)}\">Buka HTML report</a>", keyboard=True)
        elif command == "/promotion" or normalized in {"promotion", "live gate"}:
            gate = evaluate_promotion(self.paper.get_summary(refresh=False))
            self.send(chat_id, f"🔐 <b>Live Promotion Gate</b>\nReady: <b>{gate['ready_for_live']}</b>\nTrades: {gate['closed_trades']}\nWin rate: {gate['win_rate_pct']:.2f}%\nProfit factor: {gate['profit_factor']:.2f}\nMax consecutive loss: {gate['max_consecutive_losses']}\nAlasan: " + "; ".join(gate["reasons"]), keyboard=True)
        else:
            context = self.market_context(symbol)
            context["recent_conversation"] = getattr(self, "conversation", [])[-4:]
            answer = chat_with_gemini(text, context)
            if not is_failure(answer):
                self.conversation = (getattr(self, "conversation", []) + [{"user": text[:800], "assistant": answer[:1200]}])[-4:]
            self.send(chat_id, f"🤖 <b>INETCRYP Assistant</b>\n\n{html.escape(answer)}", keyboard=True)

    def run_forever(self) -> None:
        if not self.token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN belum dikonfigurasi")
        self._call("deleteWebhook", {"drop_pending_updates": "false"})
        while True:
            try:
                for update in self._call("getUpdates", {"timeout": 25, "offset": self.offset}):
                    self.offset = int(update.get("update_id", 0)) + 1
                    if update.get("message"):
                        self.handle(update["message"])
            except Exception:
                time.sleep(5)


if __name__ == "__main__":
    TelegramWorker().run_forever()
