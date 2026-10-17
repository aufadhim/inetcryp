import sys
import html
from engine.telegram_bot import send_telegram_alert

url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8091/latest.html"
dashboard = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8090/"
message = (f"🌐 <b>INETCRYP Public Access</b>\n\n"
           f"🖥 <a href=\"{html.escape(dashboard, quote=True)}\">Buka dashboard penuh</a>\n"
           f"📊 <a href=\"{html.escape(url, quote=True)}\">Buka report lengkap</a>\n\n"
           "API dashboard tetap dilindungi password. Mode Binance: read-only.")
ok = send_telegram_alert(message)
print("telegram_public_links_sent=" + str(ok).lower())
