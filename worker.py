"""24/7 read-only paper trading and alert worker."""
import os
import time
import json
import html
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from engine.paper_trader import CryptoPaperTrader
from engine.binance_client import BinanceClient
from engine.telegram_bot import send_telegram_alert
from engine.strategy_adviser import advise_after_losses
from engine.report_url import get_report_url
from engine.report_generator import write_latest_report
from engine.metrics import calculate_crypto_metrics, summarize_crypto_ticker
from engine.signal_engine import score_signal
from engine.intraday import STRATEGY
from engine.dynamic_universe import DynamicUniverse, VERSION


def refresh_commission_audit(client, symbols):
    from pathlib import Path
    commission_path=Path("data/lab/commission-audit.json")
    old=json.loads(commission_path.read_text(encoding="utf-8")) if commission_path.exists() else {}
    if not commission_path.exists() or old.get("mode")!="production_read_only" or time.time()-commission_path.stat().st_mtime>21600:
        from engine.commission_audit import audit_commissions
        from research_lab_worker import atomic
        atomic(commission_path,audit_commissions(client,symbols))


def main() -> None:
    client = BinanceClient()
    refresh_commission_audit(client,["BTCUSDT","ETHUSDT","SOLUSDT"])
    from engine.gemini_config import probe_access_once, probe_conversation
    probe_access_once()
    probe_conversation()
    trader = CryptoPaperTrader(client=client)
    universe = DynamicUniverse()
    trader.max_open_positions = 5
    trader.max_alloc = min(trader.max_alloc, 50.0)
    trader.universe_version = VERSION
    interval = max(60, int(os.getenv("PAPER_SCAN_INTERVAL_SECONDS", "300")))
    last_report_slot = ""
    while True:
        try:
            os.makedirs("data", exist_ok=True)
            with open("data/worker_status.json.tmp", "w", encoding="utf-8") as handle:
                json.dump({"status": "running", "strategy": STRATEGY, "accounting_version": "net_costs_v1", "last_heartbeat": datetime.now(timezone.utc).isoformat()}, handle)
            os.replace("data/worker_status.json.tmp", "data/worker_status.json")
            try:
                selection = universe.select()
            except Exception:
                selection = {"symbols": [], "as_of": None}
            trader.universe_as_of = selection["as_of"]
            # Existing runtime credentials only; no order/test-order endpoint.
            refresh_commission_audit(client,["BTCUSDT","ETHUSDT","SOLUSDT"]+selection["symbols"])
            result = trader.run_eval_cycle(symbols=selection["symbols"], timeframe=os.getenv("PAPER_TIMEFRAME", "15m"))
            # Reuse the normal application's adviser environment; research
            # worker itself only accesses public market data.
            try:
                from engine.research_lab import Registry
                from research_lab_worker import adviser
                registry = Registry()
                try:
                    adviser(registry)
                finally:
                    registry.db.close()
            except Exception:
                pass
            advice = advise_after_losses(result["summary"])
            if advice and os.getenv("TELEGRAM_ALERT_ENABLED", "false").lower() == "true":
                send_telegram_alert(f"🧠 <b>Gemini Strategy Adviser</b>\n{html.escape(advice[:3500])}")
            now = datetime.now(ZoneInfo("Asia/Jakarta"))
            slot = now.strftime("%Y-%m-%d-%H")
            # Crypto has no close: publish a four-hour digest on aligned UTC hours,
            # and a daily digest at 08:00 Asia/Jakarta.
            if not last_report_slot or (now.hour % 4 == 0 and slot != last_report_slot):
                signals = []
                for symbol in selection["symbols"][:10]:
                    frame = client.get_klines(symbol, "1h", 80)
                    if not frame.empty:
                        summary = summarize_crypto_ticker(symbol, calculate_crypto_metrics(frame))
                        signals.append({"symbol": symbol, **score_signal(summary)})
                report_path = write_latest_report(result["summary"], signals)
                last_report_slot = slot
                if os.getenv("TELEGRAM_ALERT_ENABLED", "false").lower() == "true":
                    report_url = get_report_url()
                    send_telegram_alert(f"📊 INETCRYP digest tersedia: {report_url}\nPair dipantau: {len(signals)}")
            for note in result.get("notifications", []):
                if os.getenv("TELEGRAM_ALERT_ENABLED", "false").lower() == "true":
                    send_telegram_alert(note)
        except Exception as exc:
            os.makedirs("data", exist_ok=True)
            with open("data/worker_status.json.tmp", "w", encoding="utf-8") as handle:
                json.dump({"status": "error", "last_error": str(exc)[:180], "last_heartbeat": datetime.now(timezone.utc).isoformat()}, handle)
            os.replace("data/worker_status.json.tmp", "data/worker_status.json")
            if os.getenv("TELEGRAM_ALERT_ENABLED", "false").lower() == "true":
                send_telegram_alert(f"⚠️ INETCRYP worker error: {str(exc)[:180]}")
        time.sleep(interval)


if __name__ == "__main__":
    main()
