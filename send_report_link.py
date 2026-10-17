import sys
from engine.telegram_bot import send_telegram_alert

url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8091/latest.html"
message = f"📊 <b>INETCRYP Report HTML</b>\n\n🔗 <a href=\"{url}\">Buka laporan terbaru</a>\n\nDashboard lokal: <code>http://127.0.0.1:8090</code>\nMode: read-only"
ok = send_telegram_alert(message)
print("telegram_report_link_sent=" + str(ok).lower())
