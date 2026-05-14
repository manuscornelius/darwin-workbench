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
    "-NonInteractive -WindowStyle Minimized -Command `"cd '$InstallDir\services\council'; .\.venv\Scripts\Activate.ps1; `$env:DYNAMODB_TABLE='darwin-workbench-prod'; `$env:STORAGE_PROVIDER='dynamodb'; `$env:LLM_PROVIDER='bedrock'; `$env:BEDROCK_MODEL_ID='us.anthropic.claude-sonnet-4-6'; `$env:AWS_REGION='us-east-1'; `$env:EPM_CONNECT_URL='http://127.0.0.1:8000/mcp'; `$env:EPM_CONNECT_AUTH_TOKEN='DarwinWorkbench2026!'; `$env:COUNCIL_PORT='8001'; python main.py`"" `
    -WindowStyle Minimized

Start-Sleep -Seconds 3

# Start nginx
Write-Step "Starting nginx"
$nginxPath = (Get-ChildItem "C:\tools" -Directory | Where-Object { $_.Name -like "nginx*" } | Select-Object -First 1).FullName
Start-Process "$nginxPath\nginx.exe" -WindowStyle Hidden

Start-Sleep -Seconds 2

Write-Host "`n==> All services started." -ForegroundColor Green
Write-Host "    Open your browser at http://localhost:5173" -ForegroundColor Yellow

# Open browser
Start-Process "http://localhost:5173"
