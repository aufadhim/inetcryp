$ErrorActionPreference = 'Continue'
$TaskName = 'INETCRYP-24x7'
& schtasks.exe /End /TN $TaskName | Out-Host
& schtasks.exe /Delete /TN $TaskName /F | Out-Host
& powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'stop_service_processes.ps1') | Out-Host
Write-Host "INETCRYP service task removed."
