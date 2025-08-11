param(
    [Parameter(Mandatory = $true)]
    [string]$ResourceGroupName,

    [Parameter(Mandatory = $true)]
    [string]$Repo, # format: owner/repo

    [Parameter(Mandatory = $false)]
    [string]$Branch = "main",

    [Parameter(Mandatory = $false)]
    [string]$SubscriptionId,

    [Parameter(Mandatory = $false)]
    [string]$AppDisplayName,

    [Parameter(Mandatory = $false)]
    [string]$AcrName
)

Write-Host "🔧 Configuring GitHub OIDC + repo secrets for CI/CD..." -ForegroundColor Yellow

function Require-Tool {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required tool not found: $Name"
    }
}

Require-Tool az
Require-Tool gh

# Ensure GitHub CLI is authenticated
function Ensure-GhAuth {
    gh auth status -h github.com 1>$null 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "GitHub CLI is not authenticated. Run 'gh auth login' or set GH_TOKEN, then re-run this script."
    }
}

# Helper to set a repo secret with error handling
function Set-RepoSecret {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$Repo
    )
    gh secret set $Name -R $Repo -b $Value 1>$null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to set GitHub secret '$Name'. Ensure you have admin access to $Repo and that 'gh auth login' succeeded."
    }
}

# Ensure we're in the deployment folder to find values.yaml if present
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

# Azure context
try {
    $account = az account show -o json | ConvertFrom-Json
} catch {
    throw "Please run 'az login' first. Error: $_"
}

if (-not $SubscriptionId) { $SubscriptionId = $account.id }
$TenantId = $account.tenantId

# Resolve ACR details via values.yaml, explicit parameter, or Azure queries
$acrName = $null
$acrLoginServer = $null
if (Test-Path "values.yaml") {
    $values = Get-Content "values.yaml" -Raw
    $acrName = ($values | Select-String 'acrName: "([^"]+)"').Matches.Groups[1].Value
    $acrLoginServer = ($values | Select-String 'acrLoginServer: "([^"]+)"').Matches.Groups[1].Value
}
# Explicit parameter takes precedence
if ($AcrName) { $acrName = $AcrName }

if (-not $acrName) {
    # Try finding ACR in the specified resource group first
    $rgAcrName = az acr list -g $ResourceGroupName --query "[0].name" -o tsv 2>$null
    if ($rgAcrName) {
        $acrName = $rgAcrName
    } else {
        # Fall back to subscription-wide discovery
        $acrListJson = az acr list -o json 2>$null
        $acrList = @()
        if ($acrListJson) {
            try { $acrList = $acrListJson | ConvertFrom-Json } catch { $acrList = @() }
        }
        if ($acrList.Count -eq 1) {
            $acrName = $acrList[0].name
        } elseif ($acrList.Count -gt 1) {
            throw "Multiple ACRs found in the subscription. Please specify one with -AcrName."
        }
    }
}
if (-not $acrLoginServer -and $acrName) {
    $acrLoginServer = az acr show --name $acrName --query loginServer -o tsv
}
if (-not $acrName -or -not $acrLoginServer) {
    throw "Could not resolve ACR details. Ensure an ACR exists in your subscription, or pass -AcrName <name>."
}
$acrId = az acr show --name $acrName --query id -o tsv

# App registration for OIDC
if (-not $AppDisplayName) { $AppDisplayName = "$ResourceGroupName-respondr-ci" }

Write-Host "Checking for app registration '$AppDisplayName'..." -ForegroundColor Yellow
$app = az ad app list --display-name $AppDisplayName -o json | ConvertFrom-Json | Select-Object -First 1
if (-not $app) {
    Write-Host "Creating app registration..." -ForegroundColor Yellow
    $app = az ad app create --display-name $AppDisplayName -o json | ConvertFrom-Json
}
$appId = $app.appId
$appObjId = $app.id

# Ensure service principal exists for the app
Write-Host "Ensuring service principal exists..." -ForegroundColor Yellow
$sp = az ad sp list --filter "appId eq '$appId'" -o json | ConvertFrom-Json | Select-Object -First 1
if (-not $sp) {
    $sp = az ad sp create --id $appId -o json | ConvertFrom-Json
}

# Assign AcrPush on the ACR
Write-Host "Assigning 'AcrPush' to SP on ACR scope..." -ForegroundColor Yellow
az role assignment create --assignee $appId --role AcrPush --scope $acrId 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Role assignment may already exist; continuing." -ForegroundColor Yellow
}

# Create federated credentials for the repo (push to branch and PRs)
$issuer = "https://token.actions.githubusercontent.com"
$audiences = @("api://AzureADTokenExchange")

function Ensure-FedCred {
    param([string]$Name, [string]$Subject)
    $existing = az ad app federated-credential list --id $appObjId -o json | ConvertFrom-Json | Where-Object { $_.name -eq $Name }
    if ($existing) {
        Write-Host "Federated credential '$Name' exists" -ForegroundColor Green
        return
    }
    $payload = @{ name = $Name; issuer = $issuer; subject = $Subject; audiences = $audiences } | ConvertTo-Json -Depth 3
    $tmp = New-TemporaryFile
    Set-Content -Path $tmp -Value $payload -Encoding utf8
    Write-Host "Creating federated credential '$Name' with subject '$Subject'"
    az ad app federated-credential create --id $appObjId --parameters @$tmp | Out-Null
    Remove-Item $tmp -Force
    Write-Host "Created federated credential '$Name'" -ForegroundColor Green
}

$owner,$repoName = $Repo.Split('/')
if (-not $owner -or -not $repoName) { throw "Repo must be in 'owner/repo' format" }

$repoFullName = "$owner/$repoName"
# Support comma-separated branches (e.g., "main,preprod")
$branches = $Branch -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ }
if ($branches.Count -eq 0) { $branches = @('main') }
foreach ($b in $branches) {
    Ensure-FedCred -Name "push-$b" -Subject "repo:$repoFullName`:ref:refs/heads/$b"
}
Ensure-FedCred -Name "pull-request" -Subject "repo:$repoFullName`:pull_request"

# Set GitHub repo secrets
Write-Host "Setting GitHub repo secrets via gh CLI..." -ForegroundColor Yellow
Ensure-GhAuth
Set-RepoSecret -Name AZURE_CLIENT_ID -Value $appId -Repo $Repo
Set-RepoSecret -Name AZURE_TENANT_ID -Value $TenantId -Repo $Repo
Set-RepoSecret -Name AZURE_SUBSCRIPTION_ID -Value $SubscriptionId -Repo $Repo
Set-RepoSecret -Name ACR_NAME -Value $acrName -Repo $Repo
Set-RepoSecret -Name ACR_LOGIN_SERVER -Value $acrLoginServer -Repo $Repo

Write-Host "✅ GitHub OIDC and repo secrets configured." -ForegroundColor Green
