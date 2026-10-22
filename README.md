# INETCRYP

Workspace analitik crypto, riset strategi, dan paper trading 24/7.
**Tidak menjanjikan profit harian. Skor bukan bukti aktivitas paus.**

## Dashboard

Navigasi responsif desktop/HP: Ringkasan, Radar peluang, Terminal pasar,
Screener, Backtest, Portofolio paper, Research Lab, dan Bot & Telegram.
Terminal menyediakan candlestick, LPM/VWAP, volume, orderbook dan transaksi
besar. Diagnostik riset tersedia dalam detail terpisah dari ringkasan.

## Riset dan pembelajaran

Research worker menguji EMA pullback, channel breakout, RSI reversion,
VWAP reclaim, flow breakout, dan compression. Eksperimen dibatasi, parameter
dibekukan, dan kandidat diuji dengan pemisahan waktu serta holdout baru.
Evaluasi mencakup fee, spread, slippage, dampak volume, biaya dua kali lipat,
latensi, drawdown, dan baseline cash/buy-and-hold dengan batas eksposur.

Pencarian harian adalah eksplorasi, bukan validasi independen. Online learner
mempelajari label masa depan yang sudah matang; model kontrol dan radar
dinamis dipisahkan. Banyaknya sampel tidak otomatis berarti bukti independen.
Gemini berperan sebagai penasihat/proposal terbatas, bukan pengubah kode atau
pelaksana order otomatis. Ketersediaannya bergantung akses model dan API.

Promosi champion **paper** memerlukan gate backtest dan forward; tidak ada
promosi otomatis ke uang asli. Tanpa kandidat lolos, sistem boleh tidak entry.

## Paper anomali terpisah

Adaptasi sebagian ide screener anomali, **bukan kloning lengkap FluxScout**.
Monitor menguji LONG dengan identitas Binance spot terverifikasi melalui depth
yang benar-benar diterima. Akun ini tidak mereset akun paper utama.

- Modal virtual awal $1.000; $50 per entry termasuk fee; maksimal lima posisi.
- Asumsi fee 0,1% per sisi, bukan tarif akun yang telah dipastikan.
- Stop -1,5% net, target +3% net, batas waktu dua jam.
- SL+ aktif setelah net liquidation +1%, pemicu +0,2%; gap tetap bisa rugi.
- Entry baru ditahan setelah kerugian realized harian $10.
- Quote stale/likuiditas kurang ditolak. Tanpa quote keluar, posisi tetap
  terbuka; tidak ada fill fiktif pada harga stop.
- SHORT dan DEX dengan biaya/jalur jual belum terverifikasi tetap observasi.

Hasil: `data/lab/anomaly-paper.json`. Ini eksperimen prospektif, bukan bukti
profit atau backtest orderbook/on-chain historis yang belum tersedia.
Tidak ada pembaca akun/channel Telegram FluxScout yang diaktifkan.

## Sumber dan keterbatasan

Binance menyediakan data pasar dan akses akun read-only bila dikonfigurasi.
CoinGecko untuk metadata/pasar, DEXScreener untuk observasi pair DEX; sumber
tambahan meliputi snapshot lintas exchange dan pemeriksaan keamanan token.
Cakupan tidak meliputi semua chain, wallet, OTC atau hidden liquidity.
HTTP 429 dapat menunda radar; cache lama tidak dianggap data segar.
LPM, VWAP dan ketimpangan orderbook adalah proksi, bukan identitas/modal pasti paus.

Jurnal mencatat hasil negatif dan pengukuran terlewat. Target hit dan harga
tertinggi setelah sinyal tidak sama dengan profit portofolio bersih.

## Menjalankan lokal (Windows)

Python 3.12 direkomendasikan:

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m uvicorn server:app --host 127.0.0.1 --port 8090
```

Dashboard: <http://127.0.0.1:8090/>. Konfigurasikan rahasia secara lokal;
jangan unggah `.env`. `start.bat` menjalankan server, paper dan Telegram,
**bukan seluruh Research Lab**. Jangan jalankan bersamaan dengan service aktif.

## Service 24/7

Deployment Windows menggunakan `C:\inetcryp` dan Task Scheduler
`INETCRYP-24x7` sebagai SYSTEM. Setelah meninjau konfigurasi/path, jalankan
dari PowerShell Administrator:

```powershell
.\install_service.ps1
```

`service_supervisor.ps1` memantau web, paper, Telegram, report,
monitor/research/collector, compression research dan narrative radar;
proses yang berhenti dijalankan ulang. Monitor berjeda 30 detik;
research/collector 300 detik **setelah tiap siklus selesai**. Backtest tidak
diulang setiap detik: hasil tersimpan dan batas API dihormati.
Komputer harus tetap menyala, tidak sleep, dan memakai jaringan yang diizinkan.

Jika `cloudflared` terpasang pada path yang dikonfigurasi, supervisor membuka
Quick Tunnel. URL bisa berubah saat restart; bukan domain permanen atau jaminan
uptime. Lindungi dashboard publik dengan `ACCESS_PASSWORD` dan origin spesifik.

## Keamanan

- Pertahankan Binance read-only, tanpa withdrawal; pengujian tetap paper.
- Jangan commit `.env`, API key, password, sesi Telegram, log atau database akun.
- `data/` adalah state lokal; backup secara aman sebelum migrasi/redeploy.
- Jangan mengekspos data akun melalui tunnel tanpa autentikasi.
- Respons provider/skor tidak menjamin keamanan token DEX.

## Pengujian

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -q
node --test tests/api-auth.test.cjs
node --check static/js/workspace.js
```

Tes mencakup biaya, timing kausal, data stale, forward gate, radar/learning,
SL+, autentikasi frontend, dan struktur navigasi. Lolos tes bukan bukti profit.

## Dokumentasi modul

- [Riset harian](RESEARCH_DAILY.md)
- [Audit biaya eksekusi](EXECUTION_AUDIT.md)
- [Eksperimen exit](EXIT_RESEARCH.md)
- [Online learning](ONLINE_LEARNING.md)
- [Opportunity radar](OPPORTUNITY_RADAR.md)
- [Anomaly radar](ANOMALY_RADAR.md)
- [Paper anomali](ANOMALY_PAPER.md)
