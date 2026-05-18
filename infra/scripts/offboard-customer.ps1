<#
.SYNOPSIS
    Remove a Darwin AI customer — terminates their Workspace and
    deletes their credentials from Secrets Manager.
    The shared infrastructure (VPC, Simple AD, DynamoDB) is not touched.

.EXAMPLE
    .\offboard-customer.ps1 -CustomerName "acme"
#>

param(
    [Parameter(Mandatory)] [string] $CustomerName,
    [string] $Region = "us-east-1"
)

$ErrorActionPreference = "Stop"
$TerraformDir = "$PSScriptRoot\..\terraform\customer"

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-OK($msg)   { Write-Host "    OK: $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "    WARN: $msg" -ForegroundColor Yellow }

# ---------------------------------------------------------------------------
# Step 1 - Load customer record and confirm
# ---------------------------------------------------------------------------
Write-Step "Loading customer record"

$registryPath = "$PSScriptRoot\..\state\customers.json"
if (-not (Test-Path $registryPath)) {
    throw "No customer registry found at $registryPath"
}

$registryRaw = Get-Content $registryPath | ConvertFrom-Json
$registry = @{}
foreach ($key in $registryRaw.PSObject.Properties.Name) {
    $registry[$key] = $registryRaw.$key
}
if (-not $registry.ContainsKey($CustomerName)) {
    throw "Customer '$CustomerName' not found in registry."
}

$customer = $registry[$CustomerName]

Write-Host ""
Write-Host "  WARNING: This will permanently terminate the Workspace for:" -ForegroundColor Red
Write-Host "  Customer:     $($customer.customer_full)" -ForegroundColor White
Write-Host "  Slug:         $CustomerName" -ForegroundColor White
Write-Host "  Workspace ID: $($customer.workspace_id)" -ForegroundColor White
Write-Host "  All session data in DynamoDB will be preserved." -ForegroundColor Gray
Write-Host ""
$confirm = Read-Host "  Type the slug '$CustomerName' to confirm offboarding"

if ($confirm -ne $CustomerName) {
    Write-Host "Offboarding cancelled." -ForegroundColor Yellow
    exit 0
}

# ---------------------------------------------------------------------------
# Step 2 - Terminate the Workspace via AWS CLI
# (Workspace was created via AWS CLI in onboard-customer.ps1, not via
# Terraform, so it is not present in the tfstate file.)
# ---------------------------------------------------------------------------
Write-Step "Terminating customer Workspace via AWS CLI"

# AWS CLI shorthand (WorkspaceId=ws-xxx) is unreliable on PS 5.1 / AWS CLI v2
# on Windows — the shorthand parser sometimes treats the entire literal string
# as the WorkspaceId value. Build the request as JSON and pass via file://.
$terminateRequest = @(
    @{ WorkspaceId = $customer.workspace_id }
)
$terminateJsonPath = Join-Path $env:TEMP "terminate-$CustomerName-$([guid]::NewGuid().ToString('N')).json"
[System.IO.File]::WriteAllText(
    $terminateJsonPath,
    (ConvertTo-Json -InputObject $terminateRequest -Depth 5),
    [System.Text.UTF8Encoding]::new($false)
)
$terminateJsonFileUri = "file://" + ($terminateJsonPath -replace '\\', '/')

try {
    aws workspaces terminate-workspaces `
        --terminate-workspace-requests $terminateJsonFileUri `
        --region $Region | Out-Null
} finally {
    if (Test-Path $terminateJsonPath) { Remove-Item $terminateJsonPath -Force }
}

# Poll until the Workspace reaches TERMINATED (or describe-workspaces stops
# returning it). Termination usually takes 2-5 minutes.
$maxWaitMinutes = 10
$waitedSeconds = 0
$intervalSeconds = 30
$wsState = $null

while ($waitedSeconds -lt ($maxWaitMinutes * 60)) {
    $wsState = aws workspaces describe-workspaces `
        --workspace-ids $customer.workspace_id `
        --region $Region `
        --query "Workspaces[0].State" `
        --output text 2>$null

    Write-Host "    [$([int]($waitedSeconds/60))m] Workspace state: $wsState" -ForegroundColor Gray

    if (-not $wsState -or $wsState -eq "TERMINATED" -or $wsState -eq "None") {
        break
    }

    Start-Sleep -Seconds $intervalSeconds
    $waitedSeconds += $intervalSeconds
}

Write-OK "Workspace terminated: $($customer.workspace_id)"

# ---------------------------------------------------------------------------
# Step 3 - Destroy the Secrets Manager entries via Terraform
# ---------------------------------------------------------------------------
Write-Step "Destroying Secrets Manager entries via Terraform"

Push-Location $TerraformDir
try {
    terraform init -reconfigure `
        -backend-config="path=$PSScriptRoot\..\state\$CustomerName.tfstate" `
        | Out-Host

    terraform destroy `
        -var="customer_name=$CustomerName" `
        -var="customer_full=$($customer.customer_full)" `
        -var="bpc_server_url=$($customer.bpc_server_url)" `
        -var="bpc_username=removed" `
        -var="bpc_password=removed" `
        -var="bpc_environment=$($customer.bpc_environment)" `
        -auto-approve `
        | Out-Host
} finally {
    Pop-Location
}

Write-OK "Secrets Manager entries destroyed"

# ---------------------------------------------------------------------------
# Step 4 - Remove from registry
# ---------------------------------------------------------------------------
Write-Step "Removing from customer registry"

$registry.Remove($CustomerName)

[System.IO.File]::WriteAllText(
    $registryPath,
    ($registry | ConvertTo-Json -Depth 5),
    [System.Text.UTF8Encoding]::new($false)
)

# Archive the state file rather than delete it
$statePath = "$PSScriptRoot\..\state\$CustomerName.tfstate"
if (Test-Path $statePath) {
    $archivePath = "$PSScriptRoot\..\state\archived\$CustomerName-$(Get-Date -Format 'yyyyMMdd').tfstate"
    $archiveDir = Split-Path $archivePath
    if (-not (Test-Path $archiveDir)) {
        New-Item -ItemType Directory -Path $archiveDir -Force | Out-Null
    }
    Move-Item $statePath $archivePath
    Write-OK "State file archived to $archivePath"
}

Write-OK "Customer removed from registry"

# ---------------------------------------------------------------------------
# Step 5 - Summary
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  Offboarding complete: $($customer.customer_full)" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Workspace terminated:  $($customer.workspace_id)" -ForegroundColor White
Write-Host "  Secrets deleted:       darwin-workbench/customers/$CustomerName/bpc" -ForegroundColor White
Write-Host "  DynamoDB data:         Preserved (sessions retained)" -ForegroundColor Gray
Write-Host "  State archived:        state\archived\$CustomerName-*.tfstate" -ForegroundColor Gray
Write-Host ""
Write-Host "  The shared infrastructure is untouched." -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
