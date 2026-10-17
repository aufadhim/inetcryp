$ErrorActionPreference = 'Stop'
$AppRoot = 'C:\inetcryp'
$Supervisor = Join-Path $AppRoot 'service_supervisor.ps1'
$TaskName = 'INETCRYP-24x7'
$Action = "powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File `"$Supervisor`""

& schtasks.exe /Create /TN $TaskName /TR $Action /SC ONSTART /RU SYSTEM /RL HIGHEST /F | Out-Host
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries
Set-ScheduledTask -TaskName $TaskName -Settings $settings | Out-Null
Write-Host "INETCRYP service task registered: $TaskName"
Write-Host "Starting service..."
& schtasks.exe /Run /TN $TaskName | Out-Host
Write-Host "Use uninstall_service.ps1 to remove it."
