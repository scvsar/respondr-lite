param(
    [Parameter(Mandatory = $true)]
    [string]$ResourceGroupName,
    
    [Parameter(Mandatory = $true)]
    [string]$Domain,
    
    [string]$Namespace = "respondr"
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

# Get Azure OpenAI details
Write-Host "🤖 Getting Azure OpenAI details..." -ForegroundColor Green
$openAIAccount = az cognitiveservices account show -g $ResourceGroupName -n respondr-openai-account --query "{endpoint: properties.endpoint}" -o json | ConvertFrom-Json
$azureOpenAIEndpoint = $openAIAccount.endpoint

# Get deployment names
$deployments = az cognitiveservices account deployment list -g $ResourceGroupName -n respondr-openai-account --query "[].name" -o tsv
$azureOpenAIDeployment = $deployments | Select-Object -First 1

Write-Host "   Endpoint: $azureOpenAIEndpoint" -ForegroundColor White
Write-Host "   Deployment: $azureOpenAIDeployment" -ForegroundColor White

# Get OAuth2 app details if they exist
Write-Host "🔐 Getting OAuth2 configuration..." -ForegroundColor Green
$oauth2Apps = az ad app list --display-name "respondr-oauth2" --query "[].{appId:appId}" -o json | ConvertFrom-Json
if ($oauth2Apps.Length -gt 0) {
    $oauth2ClientId = $oauth2Apps[0].appId
    Write-Host "   OAuth2 Client ID: $oauth2ClientId" -ForegroundColor White
} else {
    $oauth2ClientId = ""
    Write-Host "   OAuth2 app not found - will be created during OAuth2 setup" -ForegroundColor Yellow
}

# Construct full hostname
$hostname = "respondr.$Domain"
$oauth2RedirectUrl = "https://$hostname/oauth2/callback"

# Generate values.yaml
Write-Host "📝 Generating values.yaml..." -ForegroundColor Green
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
imageTag: "latest"

# Azure OpenAI
azureOpenAIEndpoint: "$azureOpenAIEndpoint"
azureOpenAIDeployment: "$azureOpenAIDeployment"
azureOpenAIApiVersion: "2024-02-15-preview"

# OAuth2 Configuration
oauth2ClientId: "$oauth2ClientId"
oauth2TenantId: "$azureTenantId"
oauth2RedirectUrl: "$oauth2RedirectUrl"

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
