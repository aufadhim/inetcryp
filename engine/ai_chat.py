"""Gemini conversational crypto assistant using non-secret market context."""
import os
import requests
import json
from typing import Any, Dict
from engine.gemini_config import generate

FAILURE_PREFIXES = ("Gemini sedang terganggu", "Gemini tidak tersedia", "Gemini menerima respons",
                    "Gemini belum dikonfigurasi")


def is_failure(text):
    return text.startswith(FAILURE_PREFIXES)


def unavailable(context):
    portfolio = context.get("paper_portfolio", context.get("portfolio", {}))
    if "equity" in portfolio:
        return ("Gemini sedang terganggu setelah percobaan ulang. Ringkasan data paper (bukan analisis AI): "
                f"equity ${portfolio['equity']:,.2f}, total PnL ${portfolio.get('net_pnl_usd', 0):+.2f}, "
                f"posisi terbuka {portfolio.get('open_positions_count', 0)}. "
                "Bagian analisis belum bisa dijawab; coba lagi nanti.")
    return "Gemini sedang terganggu setelah percobaan ulang. Gunakan /paper atau /screener untuk data langsung; analisis chat belum tersedia."


def chat_with_gemini(user_message: str, context: Dict[str, Any], operation="telegram_chat") -> str:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return "Gemini belum dikonfigurasi. Saya tetap bisa membantu dengan data portfolio dan market dasar."
    context_json = json.dumps(context, ensure_ascii=False, separators=(",", ":"), default=str)
    prompt = f"""Kamu adalah asisten crypto pribadi INETCRYP. Jawab dalam Bahasa Indonesia, ringkas tapi berguna.
Jangan mengarang data, jangan menjanjikan profit, dan bedakan fakta dari opini. Jika diminta keputusan trading,
berikan skenario, risiko, invalidation, dan alasan—bukan kepastian cuan.
Data berlabel paper adalah simulasi. Data berlabel Binance adalah akun read-only. Jangan menyatakan saldo paper sebagai saldo riil.

Pesan pengguna:
{user_message}

Konteks JSON saat ini:
{context_json}

Jawab pertanyaan pengguna secara langsung. Jika pertanyaan ambigu, minta pair atau timeframe yang relevan."""
    payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"maxOutputTokens": 900}}
    try:
        response = generate(payload, api_key, operation=operation)
        if response.status_code == 200:
            candidates = response.json().get("candidates", [])
            parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
            if parts:
                return "\n".join(p["text"] for p in parts if p.get("text") and not p.get("thought")) or "Gemini tidak mengembalikan jawaban teks."
        if response.status_code in {429, 500, 502, 503, 504}:
            return unavailable(context)
        return f"Gemini tidak tersedia saat ini (HTTP {response.status_code})."
    except (requests.Timeout, requests.ConnectionError):
        return unavailable(context)
    except Exception:
        return "Gemini menerima respons yang tidak dapat diproses. Diagnostik nonrahasia sudah dicatat."
