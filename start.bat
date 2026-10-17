@echo off
title INETCRYP - 24/7 Whale Tracker Terminal
echo ========================================================
echo  INERTIA & INETCRYP - 24/7 CRYPTO WHALE TERMINAL
echo ========================================================
echo Memeriksa virtual environment...
if not exist "venv\Scripts\python.exe" (
    echo Membuat venv...
    python -m venv venv
    call venv\Scripts\activate.bat
    pip install -r requirements.txt
) else (
    call venv\Scripts\activate.bat
)

echo.
echo Menjalankan server INETCRYP pada port 8090...
start "INETCRYP Server" /min cmd /c "python -m uvicorn server:app --host 127.0.0.1 --port 8090"
echo Menjalankan worker paper trading 24/7...
start "INETCRYP Worker" /min cmd /c "python worker.py"
echo Menjalankan Telegram bot polling...
start "INETCRYP Telegram" /min cmd /c "python -m engine.telegram_worker"
echo Semua proses INETCRYP sudah dijalankan.
pause
