<#
.SYNOPSIS
    Start all Darwin AI Workbench services manually.
    Use this to start services without rebooting after installation.
#>

$InstallDir = "C:\darwin"

function Write-Step($msg) {
    Write-Host "`n==> $msg" -ForegroundColor Cyan
}

# Start epm-connect
Write-Step "Starting epm-connect"
Start-Process powershell.exe -ArgumentList `
    "-NonInteractive -WindowStyle Minimized -Command `"cd '$InstallDir\epm-connect'; .\.venv\Scripts\Activate.ps1; epm-connect`"" `
    -WindowStyle Minimized

Start-Sleep -Seconds 3

# Start council service
Write-Step "Starting council service"
Start-Process powershell.exe -ArgumentList `
    "-NonInteractive -WindowStyle Minimized -Command `"cd '$InstallDir\services\council'; .\.venv\Scripts\Activate.ps1; python main.py`"" `
    -WindowStyle Minimized

Start-Sleep -Seconds 3

# Start nginx
Write-Step "Starting nginx"
Start-Process "C:\tools\nginx\nginx.exe" -WindowStyle Hidden

Start-Sleep -Seconds 2

Write-Host "`n==> All services started." -ForegroundColor Green
Write-Host "    Open your browser at http://localhost:5173" -ForegroundColor Yellow

# Open browser
Start-Process "http://localhost:5173"
