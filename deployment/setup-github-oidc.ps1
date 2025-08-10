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
    [string]$AppDisplayName
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

# Resolve ACR details via values.yaml or Azure queries
$acrName = $null
$acrLoginServer = $null
if (Test-Path "values.yaml") {
    $values = Get-Content "values.yaml" -Raw
    $acrName = ($values | Select-String 'acrName: "([^"]+)"').Matches.Groups[1].Value
    $acrLoginServer = ($values | Select-String 'acrLoginServer: "([^"]+)"').Matches.Groups[1].Value
}
if (-not $acrName) {
    $acrName = az acr list -g $ResourceGroupName --query "[0].name" -o tsv
}
if (-not $acrLoginServer -and $acrName) {
    $acrLoginServer = az acr show --name $acrName --query loginServer -o tsv
}
if (-not $acrName -or -not $acrLoginServer) {
    throw "Could not resolve ACR details. Ensure ACR exists or values.yaml is generated."
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
    $payload = @{ name = $Name; issuer = $issuer; subject = $Subject; audiences = $audiences } | ConvertTo-Json
    $tmp = New-TemporaryFile
    Set-Content -Path $tmp -Value $payload -Encoding utf8
    az ad app federated-credential create --id $appObjId --parameters @$tmp | Out-Null
    Remove-Item $tmp -Force
    Write-Host "Created federated credential '$Name'" -ForegroundColor Green
}

$owner,$repoName = $Repo.Split('/')
if (-not $owner -or -not $repoName) { throw "Repo must be in 'owner/repo' format" }

Ensure-FedCred -Name "push-$Branch" -Subject "repo:$Repo:ref:refs/heads/$Branch"
Ensure-FedCred -Name "pull-request" -Subject "repo:$Repo:pull_request"

# Set GitHub repo secrets
Write-Host "Setting GitHub repo secrets via gh CLI..." -ForegroundColor Yellow
gh secret set AZURE_CLIENT_ID -R $Repo -b $appId | Out-Null
gh secret set AZURE_TENANT_ID -R $Repo -b $TenantId | Out-Null
gh secret set AZURE_SUBSCRIPTION_ID -R $Repo -b $SubscriptionId | Out-Null
gh secret set ACR_NAME -R $Repo -b $acrName | Out-Null
gh secret set ACR_LOGIN_SERVER -R $Repo -b $acrLoginServer | Out-Null

Write-Host "✅ GitHub OIDC and repo secrets configured." -ForegroundColor Green
