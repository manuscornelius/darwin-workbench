<#
.SYNOPSIS
    Darwin AI Workbench - Customer Onboarding Script
    Provisions a new customer Workspace and configures their BPC connection.
    Run this once per new customer from the Omen.

.PARAMETER CustomerName
    Short slug for the customer - lowercase, no spaces (e.g. acme)

.PARAMETER CustomerFull
    Full display name of the customer (e.g. Acme Corporation)

.PARAMETER BpcServerUrl
    Customer BPC server URL (e.g. https://bpc.acme.com)

.PARAMETER BpcUsername
    Customer BPC service account username (e.g. domain\svcaccount)

.PARAMETER BpcPassword
    Customer BPC service account password

.PARAMETER BpcEnvironment
    Customer BPC Environment (AppSet) name (e.g. Acme_Planning)

.PARAMETER ContactEmail
    Customer contact email - printed in the output summary for you to email

.PARAMETER Region
    AWS region (default: us-east-1)

.EXAMPLE
    .\onboard-customer.ps1 `
        -CustomerName "acme" `
        -CustomerFull "Acme Corporation" `
        -BpcServerUrl "https://bpc.acme.com" `
        -BpcUsername "ACME\svc_darwin" `
        -BpcPassword "SecurePassword123" `
        -BpcEnvironment "Acme_Planning" `
        -ContactEmail "admin@acme.com"
#>

param(
    [Parameter(Mandatory)] [string] $CustomerName,
    [Parameter(Mandatory)] [string] $CustomerFull,
    [Parameter(Mandatory)] [string] $BpcServerUrl,
    [Parameter(Mandatory)] [string] $BpcUsername,
    [Parameter(Mandatory)] [string] $BpcPassword,
    [Parameter(Mandatory)] [string] $BpcEnvironment,
    [Parameter(Mandatory)] [string] $ContactEmail,
    [string] $Region = "us-east-1"
)

$ErrorActionPreference = "Stop"
$TerraformDir = "$PSScriptRoot\..\terraform\customer"
$StartTime = Get-Date

function Write-Step($msg) {
    Write-Host "`n==> $msg" -ForegroundColor Cyan
}

function Write-OK($msg) {
    Write-Host "    OK: $msg" -ForegroundColor Green
}

function Write-Warn($msg) {
    Write-Host "    WARN: $msg" -ForegroundColor Yellow
}

# ---------------------------------------------------------------------------
# Step 1 - Validate inputs
# ---------------------------------------------------------------------------
Write-Step "Validating inputs"

if ($CustomerName -notmatch '^[a-z0-9\-]+$') {
    throw "CustomerName must be lowercase letters, numbers and hyphens only. Got: $CustomerName"
}

if ($BpcServerUrl -notmatch '^https?://') {
    throw "BpcServerUrl must start with http:// or https://. Got: $BpcServerUrl"
}

# Check terraform is available
if (-not (Get-Command terraform -ErrorAction SilentlyContinue)) {
    throw "Terraform not found. Install it with: winget install Hashicorp.Terraform"
}

# Check AWS CLI is available and credentials work
try {
    $caller = aws sts get-caller-identity --region $Region --output json | ConvertFrom-Json
    Write-OK "AWS identity confirmed: $($caller.Arn)"
} catch {
    throw "AWS CLI not configured or credentials invalid. Run: aws configure"
}

# Check if customer already exists
$existingSecret = $null
try {
    $existingSecret = aws secretsmanager describe-secret `
        --secret-id "darwin-workbench/customers/$CustomerName/bpc" `
        --region $Region `
        --output json 2>$null
} catch {
    $existingSecret = $null
}
if ($existingSecret) {
    throw "Customer '$CustomerName' already exists in Secrets Manager. Use update-customer-bpc.ps1 to update their credentials."
}

Write-OK "All inputs valid"

# ---------------------------------------------------------------------------
# Step 2 - Generate a secure initial Workspace password
# ---------------------------------------------------------------------------
Write-Step "Generating initial Workspace password"

# Build a password that meets AD complexity requirements:
# uppercase, lowercase, number, special char, min 8 chars
# Avoiding characters that cause shell escaping issues: @ ! " ' ` \
$adjectives = @("Swift","Bright","Clear","Bold","Sharp","Calm","Fast","True")
$nouns = @("Eagle","River","Cloud","Stone","Forest","Summit","Harbor","Bridge")
$adj = $adjectives[(Get-Random -Maximum $adjectives.Count)]
$noun = $nouns[(Get-Random -Maximum $nouns.Count)]
$num = Get-Random -Minimum 10 -Maximum 99
$WorkspacePassword = "${adj}${noun}${num}Dw"

Write-OK "Password generated"

# ---------------------------------------------------------------------------
# Step 3 - Terraform apply to provision Workspace and Secrets Manager secret
# ---------------------------------------------------------------------------
Write-Step "Provisioning customer Workspace via Terraform"
Write-Host "    This will take 20-30 minutes. Please wait..." -ForegroundColor Yellow

# Write a tfvars file for this customer
$tfvarsPath = "$TerraformDir\$CustomerName.tfvars"
# Escape backslashes for HCL — single backslash becomes double backslash
$HclUsername = $BpcUsername -replace '\\', '\\'
$HclPassword = $BpcPassword -replace '\\', '\\'

$tfvarsContent = @"
customer_name   = "$CustomerName"
customer_full   = "$CustomerFull"
bpc_server_url  = "$BpcServerUrl"
bpc_username    = "$HclUsername"
bpc_password    = "$HclPassword"
bpc_environment = "$BpcEnvironment"
aws_region      = "$Region"
"@
[System.IO.File]::WriteAllText($tfvarsPath, $tfvarsContent, [System.Text.UTF8Encoding]::new($false))

# Initialise and apply
Push-Location $TerraformDir
try {
    # Use a per-customer state file so customers never interfere with each other
    terraform init -reconfigure `
        -backend-config="path=$PSScriptRoot\..\..\state\$CustomerName.tfstate" `
        | Out-Host

    terraform apply `
        -var-file="$tfvarsPath" `
        -auto-approve `
        | Out-Host

    # Capture outputs
    $tfOutputRaw = terraform output -json 2>$null
    if (-not $tfOutputRaw) {
        throw "Terraform apply failed - no outputs returned. Check the errors above."
    }
    $tfOutput = $tfOutputRaw | ConvertFrom-Json
    $WorkspaceId = $tfOutput.workspace_id.value
    $WorkspaceUsername = $tfOutput.workspace_username.value
    $BpcSecretArn = $tfOutput.bpc_secret_arn.value

    if (-not $WorkspaceId) {
        throw "Terraform apply completed but no Workspace ID in outputs. Check the AWS console."
    }

} finally {
    Pop-Location
    # Remove the tfvars file so credentials don't sit on disk
    if (Test-Path $tfvarsPath) { Remove-Item $tfvarsPath -Force }
}

Write-OK "Workspace provisioned: $WorkspaceId"

# ---------------------------------------------------------------------------
# Step 4 - Wait for Workspace to reach AVAILABLE state
# ---------------------------------------------------------------------------
Write-Step "Waiting for Workspace to become available"

$maxWaitMinutes = 40
$waitedSeconds = 0
$intervalSeconds = 30

while ($waitedSeconds -lt ($maxWaitMinutes * 60)) {
    $wsState = aws workspaces describe-workspaces `
        --workspace-ids $WorkspaceId `
        --region $Region `
        --query "Workspaces[0].State" `
        --output text

    Write-Host "    [$([int]($waitedSeconds/60))m] Workspace state: $wsState" -ForegroundColor Gray

    if ($wsState -eq "AVAILABLE") {
        break
    }

    if ($wsState -eq "ERROR" -or $wsState -eq "TERMINATED") {
        throw "Workspace entered state $wsState - check AWS console for details"
    }

    Start-Sleep -Seconds $intervalSeconds
    $waitedSeconds += $intervalSeconds
}

if ($wsState -ne "AVAILABLE") {
    throw "Workspace did not reach AVAILABLE state within $maxWaitMinutes minutes"
}

Write-OK "Workspace is AVAILABLE"

# ---------------------------------------------------------------------------
# Step 5 - Reset the AD user password to the generated password
# ---------------------------------------------------------------------------
Write-Step "Setting Workspace password"

aws workspaces reset-user-password `
    --directory-id "d-90660c1382" `
    --user-name $WorkspaceUsername `
    --new-password $WorkspacePassword `
    --region $Region | Out-Null

Write-OK "Password set"

# ---------------------------------------------------------------------------
# Step 6 - Get the WorkSpaces registration code
# ---------------------------------------------------------------------------
Write-Step "Retrieving registration code"

$regCode = aws workspaces describe-workspace-directories `
    --directory-ids "d-90660c1382" `
    --region $Region `
    --query "Directories[0].RegistrationCode" `
    --output text

Write-OK "Registration code: $regCode"

# ---------------------------------------------------------------------------
# Step 7 - Record customer in a local registry file
# ---------------------------------------------------------------------------
Write-Step "Recording customer in local registry"

$registryPath = "$PSScriptRoot\..\..\state\customers.json"
$registryDir = Split-Path $registryPath

if (-not (Test-Path $registryDir)) {
    New-Item -ItemType Directory -Path $registryDir -Force | Out-Null
}

$registry = @{}
if (Test-Path $registryPath) {
    $registry = Get-Content $registryPath | ConvertFrom-Json -AsHashtable
}

$registry[$CustomerName] = @{
    customer_full    = $CustomerFull
    contact_email    = $ContactEmail
    workspace_id     = $WorkspaceId
    workspace_user   = $WorkspaceUsername
    bpc_server_url   = $BpcServerUrl
    bpc_environment  = $BpcEnvironment
    bpc_secret_arn   = $BpcSecretArn
    onboarded_at     = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
    region           = $Region
}

[System.IO.File]::WriteAllText(
    $registryPath,
    ($registry | ConvertTo-Json -Depth 5),
    [System.Text.UTF8Encoding]::new($false)
)

Write-OK "Customer recorded in state\customers.json"

# ---------------------------------------------------------------------------
# Step 8 - Print handover summary
# ---------------------------------------------------------------------------
$elapsed = [int]((Get-Date) - $StartTime).TotalMinutes

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  Darwin AI Workbench - Customer Onboarding Complete" -ForegroundColor Green
Write-Host "  Completed in ~$elapsed minutes" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Customer:          $CustomerFull" -ForegroundColor White
Write-Host "  Contact:           $ContactEmail" -ForegroundColor White
Write-Host "  Workspace ID:      $WorkspaceId" -ForegroundColor White
Write-Host ""
Write-Host "  --- Send these details to the customer ---" -ForegroundColor Yellow
Write-Host ""
Write-Host "  WorkSpaces Client: https://clients.amazonworkspaces.com/" -ForegroundColor White
Write-Host "  Registration Code: $regCode" -ForegroundColor Cyan
Write-Host "  Username:          $WorkspaceUsername" -ForegroundColor Cyan
Write-Host "  Initial Password:  $WorkspacePassword" -ForegroundColor Cyan
Write-Host ""
Write-Host "  BPC Environment:   $BpcEnvironment" -ForegroundColor White
Write-Host "  BPC Server:        $BpcServerUrl" -ForegroundColor White
Write-Host "  BPC Credentials:   $BpcSecretArn" -ForegroundColor White
Write-Host ""
Write-Host "  IMPORTANT: The customer must install the WorkSpaces client" -ForegroundColor Yellow
Write-Host "  and ask them to change their password on first login." -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Next step: install Darwin AI on their Workspace by running" -ForegroundColor White
Write-Host "  install.ps1 on the Workspace after first login." -ForegroundColor White
Write-Host "============================================================" -ForegroundColor Green
