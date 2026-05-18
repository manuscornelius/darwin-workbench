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
Write-Host "  Workspace ID: $($customer.workspace_id)" -ForegroundColor White
Write-Host "  All session data in DynamoDB will be preserved." -ForegroundColor Gray
Write-Host ""
$confirm = Read-Host "  Type the customer name to confirm offboarding"

if ($confirm -ne $CustomerName) {
    Write-Host "Offboarding cancelled." -ForegroundColor Yellow
    exit 0
}

# ---------------------------------------------------------------------------
# Step 2 - Terraform destroy the customer resources
# ---------------------------------------------------------------------------
Write-Step "Destroying customer Workspace and Secrets Manager secret via Terraform"

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

Write-OK "Workspace and secrets destroyed"

# ---------------------------------------------------------------------------
# Step 3 - Remove from registry
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
# Step 4 - Summary
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
