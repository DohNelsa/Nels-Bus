# Archives old Desktop duplicate project folders after you close all terminals and servers.
# Run: right-click -> Run with PowerShell (or from PowerShell in Nelsaproject\scripts)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "GARANTI EXPRESS — archive old Desktop project copies" -ForegroundColor Cyan
Write-Host "Active project: C:\Users\MP\Desktop\moghamo\Nelsaproject" -ForegroundColor Green
Write-Host ""

function Stop-PortListener {
    param([int]$Port)
    for ($i = 0; $i -lt 3; $i++) {
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

Write-Host "Freeing ports 8000 and 8001 (stale Django servers)..." -ForegroundColor Yellow
Stop-PortListener -Port 8000
Stop-PortListener -Port 8001
Start-Sleep -Seconds 2

$renames = @(
    @{ From = "C:\Users\MP\Desktop\Nelsaproject"; To = "_ARCHIVE_DO_NOT_USE_Nelsaproject_old" },
    @{ From = "C:\Users\MP\Desktop\NelsaNdo"; To = "_ARCHIVE_DO_NOT_USE_NelsaNdo_old" }
)

foreach ($r in $renames) {
    $from = $r.From
    $toPath = Join-Path "C:\Users\MP\Desktop" $r.To
    if (-not (Test-Path $from)) {
        Write-Host "Already gone: $from" -ForegroundColor DarkGray
        continue
    }
    if (Test-Path $toPath) {
        Write-Host "Archive name already exists: $toPath" -ForegroundColor DarkYellow
        continue
    }
    try {
        Rename-Item -Path $from -NewName $r.To -ErrorAction Stop
        Write-Host "Archived: $from -> $toPath" -ForegroundColor Green
    } catch {
        Write-Host "Could not rename $from" -ForegroundColor Red
        Write-Host "  Close File Explorer, VS Code, and any terminal in that folder, then run this script again." -ForegroundColor Yellow
        Write-Host "  Error: $($_.Exception.Message)" -ForegroundColor DarkYellow
    }
}

Write-Host ""
Write-Host "Done. Use: cd C:\Users\MP\Desktop\moghamo\Nelsaproject ; .\scripts\run-dev.ps1" -ForegroundColor Cyan
Write-Host ""
