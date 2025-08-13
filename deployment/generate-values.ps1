param(
    [Parameter(Mandatory = $true)]
    [string]$ResourceGroupName,
    
    [Parameter(Mandatory = $true)]
    [string]$Domain,
    
    [string]$Namespace = "respondr",

    [Parameter(Mandatory = $false)]
    [string]$HostPrefix = "respondr",

    [Parameter(Mandatory = $false)]
    [string]$ImageTag = "latest",

    # Optional overrides
    [string[]]$AllowedEmailDomains,
    [string[]]$AllowedAdminUsers
)

Write-Host "🔧 Generating deployment configuration from current Azure environment..." -ForegroundColor Cyan
Write-Host "Resource Group: $ResourceGroupName" -ForegroundColor Yellow
Write-Host "Domain: $Domain" -ForegroundColor Yellow

# Get current Azure context
Write-Host "📋 Getting Azure environment details..." -ForegroundColor Green
$azureContext = az account show --query "{subscriptionId: id, tenantId: tenantId}" -o json | ConvertFrom-Json
$azureSubscriptionId = $azureContext.subscriptionId
$azureTenantId = $azureContext.tenantId

Write-Host "   Subscription: $azureSubscriptionId" -ForegroundColor White
Write-Host "   Tenant: $azureTenantId" -ForegroundColor White

# Get ACR details
Write-Host "📦 Getting Container Registry details..." -ForegroundColor Green
$acrName = az acr list -g $ResourceGroupName --query "[0].name" -o tsv
$acrLoginServer = az acr show --name $acrName --query loginServer -o tsv
Write-Host "   ACR: $acrName" -ForegroundColor White
Write-Host "   Login Server: $acrLoginServer" -ForegroundColor White

# Get Azure OpenAI details (best-effort; continue on failure)
Write-Host "🤖 Getting Azure OpenAI details..." -ForegroundColor Green
$azureOpenAIEndpoint = ""
$azureOpenAIDeployment = ""
try {
    $openAIAccountRaw = az cognitiveservices account show -g $ResourceGroupName -n respondr-openai-account --query "{endpoint: properties.endpoint}" -o json 2>$null
    if ($openAIAccountRaw) {
        $openAIAccount = $openAIAccountRaw | ConvertFrom-Json
        $azureOpenAIEndpoint = $openAIAccount.endpoint
    } else {
        Write-Host "   Azure OpenAI account not found under expected name; leaving endpoint empty" -ForegroundColor Yellow
    }
    $deploymentsRaw = az cognitiveservices account deployment list -g $ResourceGroupName -n respondr-openai-account --query "[].name" -o tsv 2>$null
    if ($deploymentsRaw) { $azureOpenAIDeployment = ($deploymentsRaw | Select-Object -First 1) }
} catch {
    Write-Host "   Skipping Azure OpenAI discovery due to error: $($_.Exception.Message)" -ForegroundColor Yellow
}
Write-Host "   Endpoint: $azureOpenAIEndpoint" -ForegroundColor White
Write-Host "   Deployment: $azureOpenAIDeployment" -ForegroundColor White

# Get OAuth2 app details if they exist (best-effort; don't fail generation)
Write-Host "🔐 Getting OAuth2 configuration..." -ForegroundColor Green
$oauth2ClientId = ""
try {
    $oauth2AppsRaw = az ad app list --display-name "respondr-oauth2" --query "[].{appId:appId}" -o json 2>$null
    if ($oauth2AppsRaw) {
        $oauth2Apps = $oauth2AppsRaw | ConvertFrom-Json
        if ($oauth2Apps -and $oauth2Apps.Length -gt 0) {
            $oauth2ClientId = $oauth2Apps[0].appId
            Write-Host "   OAuth2 Client ID: $oauth2ClientId" -ForegroundColor White
        } else {
            Write-Host "   OAuth2 app not found - will be created during OAuth2 setup" -ForegroundColor Yellow
        }
    } else {
        Write-Host "   Unable to query OAuth2 app (no output) - continuing" -ForegroundColor Yellow
    }
} catch {
    Write-Host "   Skipping OAuth2 app lookup due to error: $($_.Exception.Message)" -ForegroundColor Yellow
}

# Construct full hostname
if (-not $HostPrefix -or $HostPrefix -eq "") { $HostPrefix = "respondr" }
$hostname = "$HostPrefix.$Domain"
$oauth2RedirectUrl = "https://$hostname/oauth2/callback"

# Generate values.yaml
Write-Host "📝 Generating values.yaml..." -ForegroundColor Green

# Prepare YAML for allowed email domains
$allowedEmailDomainsLines = if ($AllowedEmailDomains -and $AllowedEmailDomains.Count -gt 0) {
    ($AllowedEmailDomains | ForEach-Object { '    - "' + ($_ -replace '"', '""') + '"' }) -join "`n"
} else {
    '    - "scvsar.org"' + "`n" + '    - "rtreit.com"'
}

# Prepare YAML for allowed admin users (commented examples if none provided)
$allowedAdminUsersBlock = if ($AllowedAdminUsers -and $AllowedAdminUsers.Count -gt 0) {
    ($AllowedAdminUsers | ForEach-Object { '    - "' + ($_ -replace '"', '""') + '"' }) -join "`n"
} else {
    '    # - "alice@example.com"' + "`n" + '    # - "bob@contoso.com"'
}
$valuesContent = @"
# Environment Configuration Values
# Generated on: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
# From Azure environment: $azureTenantId

# Azure Environment
azureSubscriptionId: "$azureSubscriptionId"
azureTenantId: "$azureTenantId"
resourceGroupName: "$ResourceGroupName"

# Container Registry
acrName: "$acrName"
acrLoginServer: "$acrLoginServer"
imageName: "respondr"
imageTag: "$ImageTag"

# Azure OpenAI
azureOpenAIEndpoint: "$azureOpenAIEndpoint"
azureOpenAIDeployment: "$azureOpenAIDeployment"
azureOpenAIApiVersion: "2024-02-15-preview"

# OAuth2 Configuration
oauth2ClientId: "$oauth2ClientId"
oauth2TenantId: "$azureTenantId"
oauth2RedirectUrl: "$oauth2RedirectUrl"
multiTenantAuth: "true"
allowedEmailDomains:
$allowedEmailDomainsLines
allowedAdminUsers:
$allowedAdminUsersBlock

# Domain Configuration
domain: "$Domain"
hostname: "$hostname"

# Application Configuration
namespace: "$Namespace"
replicas: 2
useOAuth2: "true"
"@

$valuesContent | Out-File -FilePath "values.yaml" -Encoding UTF8

Write-Host "✅ Generated values.yaml with current environment configuration" -ForegroundColor Green
Write-Host ""
Write-Host "📋 Configuration Summary:" -ForegroundColor Cyan
Write-Host "   Full Image: $acrLoginServer/respondr:latest" -ForegroundColor White
Write-Host "   Hostname: $hostname" -ForegroundColor White
Write-Host "   OAuth2 Redirect: $oauth2RedirectUrl" -ForegroundColor White
Write-Host "   Tenant ID: $azureTenantId" -ForegroundColor White
Write-Host ""
Write-Host "⚠️  IMPORTANT: This values.yaml file contains environment-specific configuration" -ForegroundColor Yellow
Write-Host "   and should NEVER be committed to git. It's in .gitignore for this reason." -ForegroundColor Yellow
