import os
import requests
from typing import Dict, Any, Optional
from engine.gemini_config import generate


def analyze_with_gemini(symbol: str, metrics: Dict[str, Any]) -> str:
    """Generate smart AI reasoning using Google Gemini API."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return "⚠️ GEMINI_API_KEY belum dikonfigurasi di file .env."


    prompt = f"""Kamu adalah Senior Quantitative Crypto Trader dan Pakar Analisis Bandarmologi/Smart Money (Numpang Paus).
Tugasmu adalah menganalisis pergerakan paus pada crypto pair berikut:

- Koin: {symbol}
- Harga Terakhir: ${metrics.get('price', 0)}
- Perubahan 24h: {metrics.get('change_pct', 0)}%
- Volume 24h: ${metrics.get('volume_usdt', 0):,.2f} USDT
- LPM Score (Likely Participant Movement): {metrics.get('lpm_score', 0)} / 100
- Wyckoff Phase: {metrics.get('phase', '-')}
- Sinyal Divergensi: {metrics.get('divergence', 'NONE')}
- Volume Intensity Spike: {metrics.get('intensity', 1.0)}x rata-rata
- Modal Beli Paus (Bandar Cost / VWAP): ${metrics.get('bandar_cost', 0)}
- Jarak ke Modal Paus: {metrics.get('dist_bandar_pct', 0)}% ({metrics.get('valuation_zone', '-')})
- Orderbook Bid/Ask Ratio: {metrics.get('bid_ask_ratio', 1.0)}

Tolong berikan ulasan ringkas, tajam, dan to-the-point dalam Bahasa Indonesia dengan format:
1. 🐋 **Aktivitas Paus:** (Apakah paus sedang akumulasi diam-diam, mark-up, atau cuci piring/distribusi?)
2. 🎯 **Risk/Reward & Valuasi:** (Apakah harga saat ini murah/dekat modal paus atau sudah pucuk?)
3. ⚡ **Rekomendasi Ritel:** (Action: Buy/Wait/Take Profit, estimasi area TP dan Stop Loss darurat).
Gunakan gaya santai namun profesional dan disiplin risiko tinggi."""

    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }],
        "generationConfig": {
            "maxOutputTokens": 800
        }
    }

    try:
        resp = generate(payload, api_key, operation="market_analysis")
        if resp.status_code == 200:
            data = resp.json()
            candidates = data.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                if parts:
                    return "\n".join(p["text"] for p in parts if p.get("text") and not p.get("thought")) or "Tidak ada respon teks dari AI."
        return f"Gagal menghubungi Gemini API (Status Code: {resp.status_code})."
    except (requests.Timeout, requests.ConnectionError):
        return "Error koneksi Gemini API; detail rahasia tidak ditampilkan."
    except Exception:
        return "Respons Gemini tidak dapat diproses; diagnostik nonrahasia sudah dicatat."
