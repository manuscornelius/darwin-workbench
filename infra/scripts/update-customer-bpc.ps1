<#
.SYNOPSIS
    Update BPC credentials for an existing Darwin AI customer.
    Use when a customer changes their BPC server, credentials or Environment.

.EXAMPLE
    .\update-customer-bpc.ps1 `
        -CustomerName "acme" `
        -BpcPassword "NewPassword123"
#>

param(
    [Parameter(Mandatory)] [string] $CustomerName,
    [string] $BpcServerUrl    = "",
    [string] $BpcUsername     = "",
    [string] $BpcPassword     = "",
    [string] $BpcEnvironment  = "",
    [string] $Region          = "us-east-1"
)

$ErrorActionPreference = "Stop"

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-OK($msg)   { Write-Host "    OK: $msg" -ForegroundColor Green }

# ---------------------------------------------------------------------------
# Step 1 - Load existing customer record
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
    throw "Customer '$CustomerName' not found. Run onboard-customer.ps1 first."
}

$customer = $registry[$CustomerName]
Write-OK "Found customer: $($customer.customer_full)"

# ---------------------------------------------------------------------------
# Step 2 - Fetch current secret
# ---------------------------------------------------------------------------
Write-Step "Fetching current BPC credentials from Secrets Manager"

$secretId = "darwin-workbench/customers/$CustomerName/bpc"
$currentSecret = aws secretsmanager get-secret-value `
    --secret-id $secretId `
    --region $Region `
    --query SecretString `
    --output text | ConvertFrom-Json

# Merge — only update fields that were passed in
$newServerUrl   = if ($BpcServerUrl)   { $BpcServerUrl }   else { $currentSecret.server_url }
$newUsername    = if ($BpcUsername)    { $BpcUsername }    else { $currentSecret.username }
$newPassword    = if ($BpcPassword)    { $BpcPassword }    else { $currentSecret.password }
$newEnvironment = if ($BpcEnvironment) { $BpcEnvironment } else { $currentSecret.environment }

Write-OK "Current values loaded"

# ---------------------------------------------------------------------------
# Step 3 - Update Secrets Manager
# ---------------------------------------------------------------------------
Write-Step "Updating Secrets Manager"

$newSecret = @{
    server_url  = $newServerUrl
    username    = $newUsername
    password    = $newPassword
    environment = $newEnvironment
} | ConvertTo-Json -Compress

aws secretsmanager put-secret-value `
    --secret-id $secretId `
    --region $Region `
    --secret-string $newSecret | Out-Null

Write-OK "Secrets Manager updated"

# ---------------------------------------------------------------------------
# Step 4 - Update customer registry
# ---------------------------------------------------------------------------
Write-Step "Updating customer registry"

# PSCustomObjects don't allow adding new properties via `.name = value` —
# Add-Member -Force handles both updating existing properties and adding new ones.
$registry[$CustomerName] | Add-Member -NotePropertyName "bpc_server_url"  -NotePropertyValue $newServerUrl   -Force
$registry[$CustomerName] | Add-Member -NotePropertyName "bpc_environment" -NotePropertyValue $newEnvironment -Force
$registry[$CustomerName] | Add-Member -NotePropertyName "updated_at"      -NotePropertyValue (Get-Date -Format "yyyy-MM-dd HH:mm:ss") -Force

[System.IO.File]::WriteAllText(
    $registryPath,
    ($registry | ConvertTo-Json -Depth 5),
    [System.Text.UTF8Encoding]::new($false)
)

Write-OK "Registry updated"

# ---------------------------------------------------------------------------
# Step 5 - Remind operator to update the Workspace .env
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  BPC credentials updated for: $($customer.customer_full)" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  New BPC Server:      $newServerUrl" -ForegroundColor White
Write-Host "  New BPC Environment: $newEnvironment" -ForegroundColor White
Write-Host "  Workspace ID:        $($customer.workspace_id)" -ForegroundColor White
Write-Host ""
Write-Host "  ACTION REQUIRED:" -ForegroundColor Yellow
Write-Host "  Log into the customer Workspace and run:" -ForegroundColor Yellow
Write-Host ""
Write-Host "  aws secretsmanager get-secret-value ``" -ForegroundColor Cyan
Write-Host "    --secret-id '$secretId' ``" -ForegroundColor Cyan
Write-Host "    --region $Region ``" -ForegroundColor Cyan
Write-Host "    --query SecretString --output text" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Then rewrite C:\darwin\epm-connect\.env with the new values" -ForegroundColor Yellow
Write-Host "  and restart the epm-connect service." -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Green
