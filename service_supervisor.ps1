$ErrorActionPreference = 'Stop'
$AppRoot = 'C:\inetcryp'
$Python = Join-Path $AppRoot 'venv\Scripts\python.exe'
$Cloudflared = 'C:\Program Files (x86)\cloudflared\cloudflared.exe'
$LogRoot = Join-Path $AppRoot 'data\logs'
New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null

function Start-AppProcess([string]$Name, [string[]]$Arguments) {
    $out = Join-Path $LogRoot "$Name.out.log"
    $err = Join-Path $LogRoot "$Name.err.log"
    Start-Process -FilePath $Python -ArgumentList $Arguments -WorkingDirectory $AppRoot -WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError $err -PassThru
}

function Write-SupervisorStatus([string]$Status, [string]$Message = '') {
    $payload = [ordered]@{
        status = $Status
        message = $Message
        updated_at = [DateTime]::UtcNow.ToString('o')
        supervisor_pid = $PID
    } | ConvertTo-Json
    [IO.File]::WriteAllText((Join-Path $AppRoot 'data\supervisor_status.json'), $payload)
}

function Test-ServerPort {
    return $null -ne (Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort 8090 -State Listen -ErrorAction SilentlyContinue)
}

function Start-Tunnel {
    $out = Join-Path $LogRoot 'cloudflared.out.log'
    $err = Join-Path $LogRoot 'cloudflared.err.log'
    return Start-Process -FilePath $Cloudflared -ArgumentList @('tunnel','--no-autoupdate','--url','http://127.0.0.1:8091') -WorkingDirectory $AppRoot -WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError $err -PassThru
}

$children = @{}
try {
    Write-SupervisorStatus 'starting'
    while ($true) {
        if ((-not (Test-ServerPort)) -and (-not $children.ContainsKey('server') -or $children['server'].HasExited)) {
            $children['server'] = Start-AppProcess 'server' @('-m','uvicorn','server:app','--host','127.0.0.1','--port','8090')
        }
        if (-not $children.ContainsKey('report') -or $children['report'].HasExited) {
            $children['report'] = Start-AppProcess 'report' @('report_server.py')
        }
        if (-not $children.ContainsKey('paper') -or $children['paper'].HasExited) {
            $children['paper'] = Start-AppProcess 'paper' @('worker.py')
        }
        if (-not $children.ContainsKey('compression-research') -or $children['compression-research'].HasExited) {
            $children['compression-research'] = Start-AppProcess 'compression-research' @('compression_research_worker.py')
        }
        if (-not $children.ContainsKey('narrative-radar') -or $children['narrative-radar'].HasExited) {
            $children['narrative-radar'] = Start-AppProcess 'narrative-radar' @('narrative_radar_worker.py')
        }
        if (-not $children.ContainsKey('telegram') -or $children['telegram'].HasExited) {
            $children['telegram'] = Start-AppProcess 'telegram' @('-m','engine.telegram_worker')
        }
        if (Test-Path $Cloudflared) {
            if (-not $children.ContainsKey('tunnel') -or $children['tunnel'].HasExited) {
                $children['tunnel'] = Start-Tunnel
                Start-Sleep -Seconds 5
                $tunnelLogs = @((Join-Path $LogRoot 'cloudflared.out.log'), (Join-Path $LogRoot 'cloudflared.err.log'))
                foreach ($tunnelLog in $tunnelLogs) {
                    if (Test-Path $tunnelLog) {
                        $match = Select-String -Path $tunnelLog -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' | Select-Object -Last 1
                        if ($match) {
                            $env:REPORT_PUBLIC_URL = "$($match.Matches[0].Value)/latest.html"
                            [IO.File]::WriteAllText((Join-Path $AppRoot 'data\public_report_url.txt'), $env:REPORT_PUBLIC_URL)
                            break
                        }
                    }
                }
                if ($env:REPORT_PUBLIC_URL) {
                        if ($children.ContainsKey('paper') -and -not $children['paper'].HasExited) {
                            Stop-Process -Id $children['paper'].Id -Force -ErrorAction SilentlyContinue
                            Start-Sleep -Seconds 1
                            $children['paper'] = Start-AppProcess 'paper' @('worker.py')
                        }
                        if ($children.ContainsKey('telegram') -and -not $children['telegram'].HasExited) {
                            Stop-Process -Id $children['telegram'].Id -Force -ErrorAction SilentlyContinue
                            Start-Sleep -Seconds 1
                            $children['telegram'] = Start-AppProcess 'telegram' @('-m','engine.telegram_worker')
                        }
                }
            }
        }
        Write-SupervisorStatus 'running'
        Start-Sleep -Seconds 10
    }
}
catch {
    Write-SupervisorStatus 'error' $_.Exception.Message
    throw
}
finally {
    foreach ($process in $children.Values) {
        if ($process -and -not $process.HasExited) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue }
    }
}
