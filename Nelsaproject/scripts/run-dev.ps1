# Start GARANTI EXPRESS locally from the correct folder.
# Stops whatever is bound to port 8000 first (stale runserver instances are a common cause
# of "Cursor changes don't show up").

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

Write-Host "Project root: $ProjectRoot" -ForegroundColor Cyan

function Stop-PortListener {
    param([int]$Port)
    for ($i = 0; $i -lt 5; $i++) {
        $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        if (-not $connections) { return }
        foreach ($conn in $connections) {
            $procId = $conn.OwningProcess
            if ($procId) {
                Write-Host "Stopping process on port ${Port} (PID $procId)..." -ForegroundColor Yellow
                Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
            }
        }
        Start-Sleep -Seconds 1
    }
}

Stop-PortListener -Port 8000
Start-Sleep -Seconds 1

if (-not (Test-Path ".env")) {
    Write-Host "Tip: copy .env.example to .env and set DJANGO_DEBUG=True for local dev." -ForegroundColor DarkYellow
}

$env:DEPLOYMENT_ENV = "development"
if (-not $env:DJANGO_DEBUG) {
    $env:DJANGO_DEBUG = "True"
}

Write-Host "Starting Django at http://127.0.0.1:8000/ (DJANGO_DEBUG=$env:DJANGO_DEBUG)" -ForegroundColor Green
python manage.py runserver 127.0.0.1:8000
