$ErrorActionPreference = 'SilentlyContinue'
$patterns = @('uvicorn server:app', 'worker.py', 'engine.telegram_worker', 'report_server.py', 'cloudflared.exe tunnel', 'service_supervisor.ps1')
Get-CimInstance Win32_Process | ForEach-Object {
    $command = [string]$_.CommandLine
    if ($command -and ($patterns | Where-Object { $command -like "*$_*" })) {
        Stop-Process -Id $_.ProcessId -Force
    }
}
