# 🐋 INETCRYP — 24/7 Crypto Whale Terminal & BandarMetrics

Platform analitik **Bandarmologi & Smart Money Tracking Crypto 24/7**, terinspirasi dari arsitektur Numpang Paus namun diadaptasi khusus untuk ekosistem cryptocurrency yang buka 24 jam nonstop setiap hari.

---

## ⚡ Fitur Utama

### 1. 📊 Terminal Radar & TradingView Charts
- **Candlestick & Anomaly Volume**: Menampilkan aksi harga real-time dengan pewarnaan anomali volume (*Purple Spike* saat transaksi $\ge 2.0\times$ rata-rata).
- **LPM (Likely Participant Movement) & Slipstream**: Sub-chart terhubung untuk memantau akumulasi bersih dan trigger cross EMA-9.
- **Whale Cost Basis (VWAP Zona Akumulasi)**: Garis putus-putus biru untuk mengukur estimasi harga modal paus crypto.
- **Wyckoff 4-Phase Classification**: Status otomatis: `AKUMULASI`, `MARK_UP`, `DISTRIBUSI`, atau `MARK_DOWN`.
- **Whale Prints Tape (> $30k)**: Mendeteksi pesanan beli/jual agresif paus secara seketika dari stream Binance.
- **Orderbook Wall Radar**: Mendeteksi letak tembok beli (*Buy Wall*) dan tembok jual (*Sell Wall*) tebal.

### 2. 🎯 Screener Paus Crypto 24/7
Menyaring seluruh koin liquid USDT di Binance dengan 5 preset instan:
- **🐋 Paus Nyerok Murah (Silent Acc)**: Bullish Divergence / LPM tinggi saat harga masih di dekat support/discount.
- **🚀 Mark-Up Breakout**: Volume Intensity $\ge 1.8\times$ dan momentum harga positif.
- **👑 Dominasi Paus**: LPM Score $\ge 58$.
- **🎯 Dekat Modal Bandar**: Jarak $\pm 3\%$ dari VWAP Paus.
- **⚠️ Bahaya Cuci Piring**: Bearish Divergence / Distribusi di pucuk.

### 3. 🧪 Simulator Backtest Historis
- Uji strategi LPM Slipstream, Bullish Divergence, atau Mark-Up Breakout pada timeframe 15m, 1h, atau 4h.
- Menghitung **Win Rate %**, **Profit Factor**, **Max Drawdown %**, dan **Jurnal Transaksi Historis**.

### 4. 🤖 Forward Tester (Paper Trading 24/7)
- Simulasi saldo virtual ($1,000 USDT) untuk forward testing terus-menerus 24 jam tanpa risiko dana riil.
- Manajemen otomatis Take Profit (+3.0%), Stop Loss (-1.5%), dan deteksi sinyal keluar dini.

### 5. 🧠 Google Gemini AI Paus
- Analisis narasi pasar dan reasoning kuantitatif aktivitas paus sekali klik menggunakan Gemini 2.5 Flash.

### 6. 📱 Telegram Bot Alert 24/7
- Kirim sinyal akumulasi paus, lonjakan volume, dan alert paper trade langsung ke Telegram kamu.

---

## 🚀 Cara Menjalankan

Cukup jalankan file:
```cmd
start.bat
```
Atau via terminal:
```bash
.\venv\Scripts\python.exe -m uvicorn server:app --host 127.0.0.1 --port 8080 --reload
```

Saat dijalankan dengan `start.bat`, tiga proses akan aktif:

- Web terminal: **`http://127.0.0.1:8090`**
- Paper worker: evaluasi portofolio otomatis sesuai `PAPER_SCAN_INTERVAL_SECONDS`
- Telegram worker: polling command `/start`, `/help`, `/signal`, `/paper`, dan `/screener`

Telegram menggunakan API publik untuk menerima pesan dan tidak membutuhkan API trading Binance.
Jangan menjalankan lebih dari satu Telegram worker dengan token yang sama.

Untuk deployment yang lebih aman, isi `ACCESS_PASSWORD`, gunakan `ALLOWED_ORIGINS` yang spesifik,
dan pertahankan API Binance dalam mode read-only.
