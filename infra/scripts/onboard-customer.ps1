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

# Check if customer already exists.
# describe-secret can still return a deleted secret for several minutes after
# force-delete-without-recovery (eventual consistency). Parse the response and
# only block if the secret exists AND is not scheduled for deletion.
$existingSecret = $null
try {
    $existingSecretRaw = aws secretsmanager describe-secret `
        --secret-id "darwin-workbench/customers/$CustomerName/bpc" `
        --region $Region `
        --output json 2>$null
    if ($existingSecretRaw) {
        $existingSecret = $existingSecretRaw | ConvertFrom-Json
    }
} catch {
    $existingSecret = $null
}
if ($existingSecret -and -not $existingSecret.DeletedDate) {
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
# Step 3 - Store BPC credentials in Secrets Manager via Terraform
# ---------------------------------------------------------------------------
Write-Step "Storing BPC credentials in Secrets Manager"

$tfvarsPath = "$TerraformDir\$CustomerName.tfvars"
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

Push-Location $TerraformDir
try {
    terraform init -reconfigure `
        -backend-config="path=$PSScriptRoot\..\..\state\$CustomerName.tfstate" `
        | Out-Host

    terraform apply `
        -var-file="$tfvarsPath" `
        -auto-approve `
        | Out-Host

    $tfOutputRaw = terraform output -json 2>$null
    if (-not $tfOutputRaw) {
        throw "Terraform apply failed - no outputs returned. Check the errors above."
    }
    $tfOutput = $tfOutputRaw | ConvertFrom-Json
    $BpcSecretArn = $tfOutput.bpc_secret_arn.value

} finally {
    Pop-Location
    if (Test-Path $tfvarsPath) { Remove-Item $tfvarsPath -Force }
}

Write-OK "BPC credentials stored: $BpcSecretArn"

# ---------------------------------------------------------------------------
# Step 4 - Provision Workspace via AWS CLI
# ---------------------------------------------------------------------------
Write-Step "Provisioning customer Workspace"
Write-Host "    This will take 20-30 minutes. Please wait..." -ForegroundColor Yellow

$adUsername = "$CustomerName-user"

# Build the create-workspaces request as a PowerShell object, serialize via
# ConvertTo-Json, and pass to AWS CLI as file:/// to avoid PowerShell 5.1's
# native command argument quoting bug (it strips embedded double quotes).
$workspaceRequest = @(
    @{
        DirectoryId = "d-90660c1382"
        UserName    = $adUsername
        BundleId    = "wsb-gm4d5tx2v"
        WorkspaceProperties = @{
            ComputeTypeName                     = "PERFORMANCE"
            RunningMode                         = "AUTO_STOP"
            RunningModeAutoStopTimeoutInMinutes = 60
            RootVolumeSizeGib                   = 80
            UserVolumeSizeGib                   = 50
        }
        Tags = @(
            @{ Key = "Customer"; Value = $CustomerName }
            @{ Key = "Project";  Value = "darwin-workbench" }
        )
    }
)

# Use -InputObject so PS 5.1 doesn't unwrap the single-element array via the
# pipeline, which would produce a bare JSON object instead of a JSON array.
$workspaceJsonText = ConvertTo-Json -InputObject $workspaceRequest -Depth 10

$workspaceJsonPath = Join-Path $env:TEMP "workspace-$CustomerName-$([guid]::NewGuid().ToString('N')).json"
[System.IO.File]::WriteAllText(
    $workspaceJsonPath,
    $workspaceJsonText,
    [System.Text.UTF8Encoding]::new($false)
)

# Debug: show exactly what we're about to send to AWS CLI
Write-Host "    Request file: $workspaceJsonPath" -ForegroundColor Gray
Write-Host "    Request body:" -ForegroundColor Gray
Get-Content $workspaceJsonPath | ForEach-Object { Write-Host "      $_" -ForegroundColor Gray }

# Use file:// (two slashes) with forward slashes. AWS CLI strips file:// and
# opens the remainder as a path; three slashes leaves a leading / which makes
# the path invalid on Windows.
$workspaceJsonFileUri = "file://" + ($workspaceJsonPath -replace '\\', '/')

try {
    $createResult = aws workspaces create-workspaces `
        --workspaces $workspaceJsonFileUri `
        --region $Region `
        --output json | ConvertFrom-Json
} finally {
    if (Test-Path $workspaceJsonPath) { Remove-Item $workspaceJsonPath -Force }
}

if ($createResult.FailedRequests -and $createResult.FailedRequests.Count -gt 0) {
    throw "Failed to create Workspace: $($createResult.FailedRequests[0].ErrorMessage)"
}

$WorkspaceId = $createResult.PendingRequests[0].WorkspaceId
$WorkspaceUsername = $adUsername
Write-OK "Workspace provisioning started: $WorkspaceId"

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

# Password reset is a Directory Service operation, not a Workspaces one
aws ds reset-user-password `
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
