import os
import requests
from typing import Optional, Dict, Any
from dotenv import load_dotenv

load_dotenv()


def send_telegram_alert(message: str, chat_id: Optional[str] = None) -> bool:
    """Send alert message to Telegram bot/channel."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    target_chat = chat_id or os.getenv("TELEGRAM_CHAT_ID", "").strip()

    if not token or not target_chat:
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": target_chat,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    try:
        resp = requests.post(url, json=payload, timeout=8)
        return resp.status_code == 200
    except Exception:
        return False


def format_whale_alert(symbol: str, signal_type: str, price: float, lpm_score: float, dist_pct: float) -> str:
    """Format rich Telegram message for whale signals."""
    if "NYEROK" in signal_type or "BULL" in signal_type:
        header = "🐋 <b>WHALE ACCUMULATION DETECTED</b>"
        action = "🟢 <b>Rekomendasi:</b> Potensi Nyerok Murah / Silent Accumulation"
    elif "MARK_UP" in signal_type or "BREAKOUT" in signal_type:
        header = "🚀 <b>MARK-UP BREAKOUT CONFIRMED</b>"
        action = "🟢 <b>Rekomendasi:</b> Momentum Beli / Ride the Wave"
    else:
        header = "⚠️ <b>WHALE DISTRIBUTION WARNING</b>"
        action = "🔴 <b>Rekomendasi:</b> Amankan Profit / Cuci Piring"

    return f"""{header}
━━━━━━━━━━━━━━━━━━
🪙 <b>Pair:</b> <code>{symbol}</code>
💰 <b>Harga Saat Ini:</b> <code>${price:,.4f}</code>
📊 <b>LPM Score:</b> <code>{lpm_score:.1f}/100</code>
🎯 <b>Jarak ke Modal Paus:</b> <code>{dist_pct:+.2f}%</code>
━━━━━━━━━━━━━━━━━━
{action}
⚡ <i>Terminal: INETCRYP 24/7 Whale Tracker</i>"""
