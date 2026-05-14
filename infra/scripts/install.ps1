<#
.SYNOPSIS
    Darwin AI Workbench - one-shot installation script.
    Run once on a fresh AWS Workspace after first login.
    Installs all dependencies, clones the repo, builds the UI,
    pulls credentials from Secrets Manager, and writes .env files.
#>

param(
    [string]$Region = "us-east-1",
    [string]$BpcSecretName = "darwin-workbench/bpc-credentials",
    [string]$CouncilSecretName = "darwin-workbench/council-service-credentials",
    [string]$DynamoTable = "darwin-workbench-prod",
    [string]$RepoUrl = "https://github.com/manuscornelius/darwin-workbench.git",
    [string]$EpmRepoUrl = "https://github.com/manuscornelius/epm-connect.git",
    [string]$InstallDir = "C:\darwin"
)

$ErrorActionPreference = "Stop"

function Write-Step($msg) {
    Write-Host "`n==> $msg" -ForegroundColor Cyan
}

function Write-OK($msg) {
    Write-Host "    OK: $msg" -ForegroundColor Green
}

# ---------------------------------------------------------------------------
# Step 1 - Install Chocolatey (package manager)
# ---------------------------------------------------------------------------
Write-Step "Installing Chocolatey"
if (-not (Get-Command choco -ErrorAction SilentlyContinue)) {
    Set-ExecutionPolicy Bypass -Scope Process -Force
    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
    Invoke-Expression ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))
    Write-OK "Chocolatey installed"
} else {
    Write-OK "Chocolatey already installed"
}

# Reload PATH
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")

# ---------------------------------------------------------------------------
# Step 2 - Install Python 3.12, Node.js, Git
# ---------------------------------------------------------------------------
Write-Step "Installing Python 3.12, Node.js 20, Git"
choco install python312 nodejs-lts git -y --no-progress
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
Write-OK "Python, Node.js, Git installed"

# ---------------------------------------------------------------------------
# Step 3 - Install uv (Python package manager)
# ---------------------------------------------------------------------------
Write-Step "Installing uv"
Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
Write-OK "uv installed"

# ---------------------------------------------------------------------------
# Step 4 - Install AWS CLI v2
# ---------------------------------------------------------------------------
Write-Step "Installing AWS CLI v2"
if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
    $awsInstaller = "$env:TEMP\awscliv2.msi"
    Invoke-WebRequest -Uri "https://awscli.amazonaws.com/AWSCLIV2.msi" -OutFile $awsInstaller
    Start-Process msiexec.exe -Wait -ArgumentList "/i $awsInstaller /quiet"
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
    Write-OK "AWS CLI installed"
} else {
    Write-OK "AWS CLI already installed"
}

# ---------------------------------------------------------------------------
# Step 5 - Clone the repo
# ---------------------------------------------------------------------------
Write-Step "Cloning darwin-workbench repo to $InstallDir"
if (Test-Path $InstallDir) {
    Write-Host "    $InstallDir already exists - pulling latest" -ForegroundColor Yellow
    cd $InstallDir
    git pull
} else {
    git clone $RepoUrl $InstallDir
}
Write-OK "Repo ready at $InstallDir"

# Clone epm-connect
Write-Step "Cloning epm-connect"
$epmRepoDir = "C:\darwin\epm-connect"
if (Test-Path $epmRepoDir) {
    Write-Host "    epm-connect already exists - pulling latest" -ForegroundColor Yellow
    cd $epmRepoDir
    git pull
} else {
    git clone $EpmRepoUrl $epmRepoDir
}
Write-OK "epm-connect ready at $epmRepoDir"

# ---------------------------------------------------------------------------
# Step 6 - Pull credentials from Secrets Manager
# ---------------------------------------------------------------------------
Write-Step "Pulling credentials from Secrets Manager"

$bpcSecret = aws secretsmanager get-secret-value `
    --secret-id $BpcSecretName `
    --region $Region `
    --query SecretString `
    --output text | ConvertFrom-Json

$councilSecret = aws secretsmanager get-secret-value `
    --secret-id $CouncilSecretName `
    --region $Region `
    --query SecretString `
    --output text | ConvertFrom-Json

Write-OK "Credentials retrieved"

# ---------------------------------------------------------------------------
# Step 7 - Configure AWS CLI with council service credentials
# ---------------------------------------------------------------------------
Write-Step "Configuring AWS credentials for council service"
aws configure set aws_access_key_id $councilSecret.aws_access_key_id
aws configure set aws_secret_access_key $councilSecret.aws_secret_access_key
aws configure set region $Region
Write-OK "AWS credentials configured"

# ---------------------------------------------------------------------------
# Step 8 - Install epm-connect
# ---------------------------------------------------------------------------
Write-Step "Installing epm-connect"
$epmDir = "$InstallDir\epm-connect"
cd $epmDir
uv venv .venv
.\.venv\Scripts\Activate.ps1
uv pip install -e .

# Write epm-connect .env
$epmEnv = "BPC_SERVER_URL=$($bpcSecret.server_url)`nBPC_USERNAME=$($bpcSecret.username)`nBPC_PASSWORD=$($bpcSecret.password)`nBPC_CLIENT_ID=$($bpcSecret.client_id)`nAUTH_TOKEN=DarwinWorkbench2026!"
[System.IO.File]::WriteAllText("$epmDir\.env", $epmEnv, [System.Text.UTF8Encoding]::new($false))

Write-OK "epm-connect installed"

# ---------------------------------------------------------------------------
# Step 8b - Create council requirements.txt if missing
# (must run before the council install in Step 9)
# ---------------------------------------------------------------------------
$councilDir = "$InstallDir\services\council"
Write-Step "Checking council requirements.txt"
$reqFile = "$councilDir\requirements.txt"
if (-not (Test-Path $reqFile)) {
    $reqContent = "fastapi`nuvicorn`nanthropic`nhttpx`npython-dotenv`npydantic`nlanggraph`npyyaml`naiosqlite`nboto3"
    [System.IO.File]::WriteAllText($reqFile, $reqContent, [System.Text.UTF8Encoding]::new($false))
    Write-OK "requirements.txt created"
} else {
    Write-OK "requirements.txt already exists"
}

# ---------------------------------------------------------------------------
# Step 9 - Install council service
# ---------------------------------------------------------------------------
Write-Step "Installing council service"
cd $councilDir
uv venv .venv
.\.venv\Scripts\Activate.ps1
uv pip install -r requirements.txt

# Write council .env
$councilEnv = "ANTHROPIC_API_KEY=`nLLM_PROVIDER=bedrock`nBEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-6`nAWS_REGION=$Region`nSTORAGE_PROVIDER=dynamodb`nDYNAMODB_TABLE=$DynamoTable`nEPM_CONNECT_URL=http://127.0.0.1:8000/mcp`nEPM_CONNECT_AUTH_TOKEN=DarwinWorkbench2026!`nCOUNCIL_PORT=8001"
[System.IO.File]::WriteAllText("$councilDir\.env", $councilEnv, [System.Text.UTF8Encoding]::new($false))

Write-OK "Council service installed"

# ---------------------------------------------------------------------------
# Step 10 - Build static UI
# ---------------------------------------------------------------------------
Write-Step "Building static UI"
$uiDir = "$InstallDir\apps\workbench-ui"
cd $uiDir
npm install
npm run build
Write-OK "Static UI built at $uiDir\dist"

# ---------------------------------------------------------------------------
# Step 11 - Install nginx to serve the static UI
# ---------------------------------------------------------------------------
Write-Step "Installing nginx"
choco install nginx -y --no-progress
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")

# Write nginx config
$nginxConf = @"
worker_processes 1;
events { worker_connections 1024; }
http {
    include mime.types;
    default_type application/octet-stream;
    server {
        listen 5173;
        root $($uiDir.Replace('\','/'))/dist;
        index index.html;
        location / {
            try_files `$uri `$uri/ /index.html;
        }
    }
}
"@
[System.IO.File]::WriteAllText("C:\tools\nginx\conf\nginx.conf", $nginxConf, [System.Text.UTF8Encoding]::new($false))
Write-OK "nginx configured"

# ---------------------------------------------------------------------------
# Step 13 - Register Task Scheduler jobs for auto-start
# ---------------------------------------------------------------------------
Write-Step "Registering auto-start Task Scheduler jobs"

# epm-connect
$epmAction = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NonInteractive -WindowStyle Hidden -Command `"cd '$epmDir'; .\.venv\Scripts\Activate.ps1; epm-connect`""
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit 0 -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask `
    -TaskName "Darwin-epm-connect" `
    -Action $epmAction `
    -Trigger $trigger `
    -Settings $settings `
    -RunLevel Highest `
    -Force | Out-Null
Write-OK "epm-connect scheduled"

# Council service
$councilAction = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NonInteractive -WindowStyle Hidden -Command `"cd '$councilDir'; .\.venv\Scripts\Activate.ps1; python main.py`""
$trigger2 = New-ScheduledTaskTrigger -AtLogOn
Register-ScheduledTask `
    -TaskName "Darwin-council" `
    -Action $councilAction `
    -Trigger $trigger2 `
    -Settings $settings `
    -RunLevel Highest `
    -Force | Out-Null
Write-OK "Council service scheduled"

# nginx (UI)
$nginxAction = New-ScheduledTaskAction `
    -Execute "C:\tools\nginx\nginx.exe"
$trigger3 = New-ScheduledTaskTrigger -AtLogOn
Register-ScheduledTask `
    -TaskName "Darwin-nginx" `
    -Action $nginxAction `
    -Trigger $trigger3 `
    -Settings $settings `
    -RunLevel Highest `
    -Force | Out-Null
Write-OK "nginx scheduled"

# ---------------------------------------------------------------------------
# Step 14 - Create desktop shortcut
# ---------------------------------------------------------------------------
Write-Step "Creating desktop shortcut"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut("$env:PUBLIC\Desktop\Darwin AI Workbench.lnk")
$shortcut.TargetPath = "http://localhost:5173"
$shortcut.Save()
Write-OK "Desktop shortcut created"

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
Write-Host "`n" -NoNewline
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  Darwin AI Workbench installation complete!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  Services will auto-start on next login." -ForegroundColor White
Write-Host "  To start now without rebooting, run:" -ForegroundColor White
Write-Host "    .\start-services.ps1" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Green
