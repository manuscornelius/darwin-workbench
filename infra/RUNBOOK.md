# Darwin AI Workbench — Operator Runbook

## Overview

This runbook covers the full customer lifecycle for the Darwin AI Workbench:
onboarding, credential updates, and offboarding. All scripts run from the
Omen using PowerShell. AWS credentials must be configured (`aws configure`).

---

## Prerequisites

- PowerShell 5.1 on the Omen
- AWS CLI configured with `mcornelius` credentials (`aws sts get-caller-identity`)
- Terraform installed (`terraform version`)
- Git installed and repo cloned at `C:\dev\darwin-workbench\`
- AWS WorkSpaces client installed for testing logins

---

## Onboarding a New Customer

### What you need from the customer before starting

- BPC server URL (e.g. `https://bpc.acme.com`)
- BPC service account username (e.g. `ACME\svc_darwin`)
- BPC service account password (no `@` or `!` characters — reset the password
  if needed to remove them, as these cause shell escaping issues)
- BPC Environment (AppSet) name (e.g. `Acme_Planning`)
- Customer contact email

### Step 1 — Choose a customer slug

Pick a short lowercase slug for the customer — no spaces, letters and hyphens
only. This becomes their username (`{slug}-user`) and Secrets Manager path.

Examples: `acme`, `contoso`, `shell-finance`

### Step 2 — Create the AD user manually (one-time per customer)

This step is required because AWS Simple AD does not support programmatic user
creation via the CLI. It only needs to be done once per customer — the user
persists even if their Workspace is later terminated and reprovisioned.

1. Go to [AWS Console → Amazon WorkSpaces](https://console.aws.amazon.com/workspaces)
2. Click **Launch WorkSpaces**
3. Select directory `d-90660c1382` (darwin.workbench.local)
4. Click **Create Users**
5. Fill in:
   - First name: `{CustomerFull}`
   - Last name: `User`
   - Username: `{slug}-user` (e.g. `acme-user`)
   - Email: customer contact email
6. Click **Create Users**
7. Click **Cancel** — do NOT proceed with the Launch wizard

> **Note:** If you are re-onboarding a customer who was previously offboarded,
> their AD user still exists. Skip this step entirely.

### Step 3 — Run the onboarding script

Open PowerShell on the Omen and run:

```powershell
cd C:\dev\darwin-workbench\infra\scripts

.\onboard-customer.ps1 `
    -CustomerName "acme" `
    -CustomerFull "Acme Corporation" `
    -BpcServerUrl "https://bpc.acme.com" `
    -BpcUsername "ACME\svc_darwin" `
    -BpcPassword "SecurePassword123" `
    -BpcEnvironment "Acme_Planning" `
    -ContactEmail "admin@acme.com"
```

The script will:
1. Validate all inputs
2. Generate a secure initial Workspace password
3. Store BPC credentials in Secrets Manager
4. Provision the Workspace (~10-12 minutes)
5. Wait for AVAILABLE state
6. Set the Workspace password
7. Print the handover details

Expected runtime: **10-15 minutes**

### Step 4 — Send the customer their login details

The script prints a handover block at the end. Copy these details and email
them to the customer:

```
WorkSpaces Client:  https://clients.amazonworkspaces.com/
Registration Code:  SLiad+VLSDAK    (shared across all customers)
Username:           acme-user
Initial Password:   {generated password}
```

Tell the customer to:
1. Download and install the WorkSpaces client
2. Register with the code above
3. Log in and change their password on first login
4. Open the browser at `http://localhost:5173`

### Step 5 — Install Darwin AI on the Workspace

After the customer logs in for the first time, connect to their Workspace
and run the install script:

```powershell
Set-ExecutionPolicy Bypass -Scope Process -Force
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
cd C:\darwin-workbench
git pull
& "C:\darwin-workbench\infra\scripts\install.ps1" `
    -BpcSecretName "darwin-workbench/customers/acme/bpc"
```

> The install script clones the repo, installs all dependencies, builds the
> UI, pulls credentials from Secrets Manager, and registers auto-start tasks.
> It takes 10-20 minutes on first run.

---

## Updating a Customer's BPC Credentials

Use this when a customer changes their BPC server, service account, or
Environment.

```powershell
cd C:\dev\darwin-workbench\infra\scripts

.\update-customer-bpc.ps1 `
    -CustomerName "acme" `
    -BpcPassword "NewPassword456"
```

You can pass any combination of `-BpcServerUrl`, `-BpcUsername`,
`-BpcPassword`, `-BpcEnvironment` — only the fields you pass will be updated.

After running, log into the customer Workspace and restart epm-connect:

```powershell
# On the customer Workspace
cd C:\darwin\epm-connect
# Update .env with new credentials from Secrets Manager
# Then restart the service
```

---

## Offboarding a Customer

Use this when a customer cancels their subscription.

```powershell
cd C:\dev\darwin-workbench\infra\scripts

.\offboard-customer.ps1 -CustomerName "acme"
```

The script will:
1. Show the customer details and ask you to type the slug to confirm
2. Terminate the Workspace (~2 minutes)
3. Delete the BPC credentials from Secrets Manager
4. Archive the Terraform state file
5. Remove the customer from the registry

> **Note:** DynamoDB session data is preserved after offboarding. This is
> intentional — it allows you to restore history if a customer re-subscribes.
> The AD user is also preserved in Simple AD.

---

## Checking Customer Status

```powershell
# List all customers
Get-Content C:\dev\darwin-workbench\infra\state\customers.json

# Check a specific Workspace state
aws workspaces describe-workspaces `
    --workspace-ids ws-xxxxxxxxx `
    --region us-east-1 `
    --query "Workspaces[0].State"
```

---

## Shared Infrastructure Reference

| Resource | ID / Name |
|---|---|
| AWS Account | 496020861906 |
| Region | us-east-1 |
| Simple AD | d-90660c1382 (darwin.workbench.local) |
| VPC | vpc-06cd57f6ff917c649 |
| DynamoDB table | darwin-workbench-prod |
| Workspace bundle | wsb-gm4d5tx2v (Performance, Win10, 2vCPU, 8GB) |
| WorkSpaces registration code | SLiad+VLSDAK |

---

## Costs per Customer

| Resource | Cost |
|---|---|
| Workspace (Performance, AutoStop) | ~$60/month |
| Secrets Manager secret | ~$0.40/month |
| DynamoDB (pay per request) | ~$0/month at low usage |
| **Total per customer** | **~$60/month** |

> AutoStop billing means the customer only pays when the Workspace is running.
> If they use it 8 hours/day the cost is the same. If they rarely use it,
> it may be lower.

---

## Troubleshooting

**Script fails with "Customer already exists in Secrets Manager"**
The previous run created the secret before failing. Delete it and retry:
```powershell
aws secretsmanager delete-secret `
    --secret-id "darwin-workbench/customers/{slug}/bpc" `
    --force-delete-without-recovery `
    --region us-east-1
```
Wait 2 minutes then run the script again.

**Workspace stays in PENDING for more than 40 minutes**
Check the AWS console for errors. Common cause: the AD user doesn't exist.
Go back to Step 2 and create the user, then run the script again.

**epm-connect fails with "EPM_CONNECT_AUTH_TOKEN must be set"**
The .env file is missing or in the wrong location. Ensure you are running
`epm-connect` from `C:\darwin\epm-connect\` and that the .env file exists
there with all required variables.

**BPC connection fails**
Verify the BPC server URL is reachable from the Workspace. Check that the
service account password contains no `@` or `!` characters.
