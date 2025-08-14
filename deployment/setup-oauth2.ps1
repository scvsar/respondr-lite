# OAuth2 Proxy Setup Script for Azure AD Integration
# This script creates an Azure AD app registration and configures oauth2-proxy for Entra authentication

param(
    [Parameter(Mandatory=$true)]
    [string]$ResourceGroupName,
    
    [Parameter(Mandatory=$false)]
    [string]$Domain = "rtreit.com",
    
    [Parameter(Mandatory=$false)]
    [string]$AppName,

    [Parameter(Mandatory=$false)]
    [string]$Namespace = "respondr",

    [Parameter(Mandatory=$false)]
    [string]$HostPrefix = "respondr"
)

Write-Host "Setting up OAuth2 Proxy with Azure AD integration..." -ForegroundColor Green
Write-Host "Resource Group: $ResourceGroupName" -ForegroundColor Cyan
Write-Host "Domain: $Domain" -ForegroundColor Cyan

# Set default app name based on domain and host prefix if not provided
if (-not $AppName) {
    $AppName = "$HostPrefix-$($Domain.Replace('.', '-'))-oauth2"
}

Write-Host "App Name: $AppName" -ForegroundColor Cyan

# Get tenant ID
$tenantId = az account show --query tenantId -o tsv
if (-not $tenantId) {
    Write-Error "Failed to get tenant ID. Make sure you're logged into Azure CLI."
    exit 1
}

if (-not $HostPrefix -or $HostPrefix -eq "") { $HostPrefix = "respondr" }
$redirectUri = "https://$HostPrefix.$Domain/oauth2/callback"
$hostname = "$HostPrefix.$Domain"

Write-Host "Tenant ID: $tenantId" -ForegroundColor Cyan
Write-Host "Redirect URI: $redirectUri" -ForegroundColor Cyan

# Check if app registration already exists
Write-Host "Checking for existing app registration..." -ForegroundColor Yellow
$existingApp = az ad app list --display-name $AppName --query "[0]" -o json 2>$null | ConvertFrom-Json

if ($existingApp) {
    Write-Host "Found existing app registration: $($existingApp.displayName)" -ForegroundColor Green
    $appId = $existingApp.appId
    
    # Update redirect URI
    Write-Host "Updating redirect URI..." -ForegroundColor Yellow
    az ad app update --id $appId --web-redirect-uris $redirectUri 2>$null
} else {
    # Create new app registration
    Write-Host "Creating new Azure AD app registration..." -ForegroundColor Yellow
    $app = az ad app create `
        --display-name $AppName `
        --web-redirect-uris $redirectUri `
        --sign-in-audience "AzureADMultipleOrgs" `
        -o json | ConvertFrom-Json
    
    if (-not $app) {
        Write-Error "Failed to create app registration"
        exit 1
    }
    
    $appId = $app.appId
    Write-Host "Created app registration with ID: $appId" -ForegroundColor Green
}

# Create/reset client secret
Write-Host "Creating client secret..." -ForegroundColor Yellow
$clientSecret = az ad app credential reset --id $appId --append --query password -o tsv

if (-not $clientSecret) {
    Write-Error "Failed to create client secret"
    exit 1
}

# Generate secure cookie secret (32 characters for AES-256)
Write-Host "Generating secure cookie secret..." -ForegroundColor Yellow
$cookieSecret = -join ((1..32) | ForEach-Object { '{0:x}' -f (Get-Random -Maximum 16) })

# Create Kubernetes namespace if it doesn't exist
Write-Host "Ensuring namespace '$Namespace' exists..." -ForegroundColor Yellow
kubectl create namespace $Namespace --dry-run=client -o yaml | kubectl apply -f -

# Create OAuth2 secrets (idempotent)
Write-Host "Creating Kubernetes secrets for OAuth2 proxy..." -ForegroundColor Yellow
kubectl -n $Namespace create secret generic oauth2-secrets `
    --from-literal=client-id=$appId `
    --from-literal=client-secret=$clientSecret `
    --from-literal=cookie-secret=$cookieSecret `
    --from-literal=tenant-id=$tenantId `
    --dry-run=client -o yaml | kubectl apply -f -

if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ OAuth2 secrets created successfully!" -ForegroundColor Green
} else {
    Write-Error "Failed to create OAuth2 secrets"
    exit 1
}

 # NOTE: Deployment file creation is now handled by process-template.ps1 using
 # the unified template (respondr-k8s-unified-template.yaml). We retain only
 # secret creation and app registration here for clarity.
Write-Host "Skipping legacy per-script deployment file generation (handled later by unified template)" -ForegroundColor Yellow

# Get ACR details
$acrName = az acr list -g $ResourceGroupName --query "[0].name" -o tsv
if ($acrName) {
    $acrLoginServer = az acr show --name $acrName --query loginServer -o tsv
    $imageUri = "$acrLoginServer/respondr:latest"
} else {
    Write-Warning "ACR not found, using placeholder image"
    $imageUri = "respondr:latest"
}

# Get workload identity details
$aksClusterName = az aks list --resource-group $ResourceGroupName --query "[0].name" -o tsv
if ($aksClusterName) {
    $identityClientId = az aks show --resource-group $ResourceGroupName --name $aksClusterName --query "identityProfile.kubeletidentity.clientId" -o tsv
} else {
    $identityClientId = "CLIENT_ID_PLACEHOLDER"
}

Write-Host "✅ OAuth2 Proxy setup (app registration + secrets) completed successfully!" -ForegroundColor Green
Write-Host ""
Write-Host "Configuration Summary:" -ForegroundColor Yellow
Write-Host "  App Registration: $AppName ($appId)" -ForegroundColor Cyan
Write-Host "  Sign-in audience: AzureADMultipleOrgs (multi-tenant)" -ForegroundColor Cyan
Write-Host "  Redirect URI: $redirectUri" -ForegroundColor Cyan
Write-Host "  Hostname: $hostname" -ForegroundColor Cyan
Write-Host "  Image: $imageUri" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next Steps:" -ForegroundColor Yellow
Write-Host "1. Continue with unified deployment generation (handled by deploy-complete/process-template)" -ForegroundColor White
Write-Host ""
Write-Host "2. Update your DNS to point to the Application Gateway IP" -ForegroundColor White
Write-Host ""
Write-Host "3. Test authentication by visiting: https://$hostname" -ForegroundColor White
Write-Host "   You should be redirected to Microsoft sign-in" -ForegroundColor Cyan
Write-Host ""
Write-Host "Authentication Flow:" -ForegroundColor Yellow
Write-Host "  User → Application Gateway → oauth2-proxy (port 4180) → Your App (port 8000)" -ForegroundColor Cyan
Write-Host "  - oauth2-proxy handles all Azure AD authentication" -ForegroundColor Cyan
Write-Host "  - Your application receives authenticated requests with user headers" -ForegroundColor Cyan
Write-Host "  - No changes needed to your existing FastAPI application!" -ForegroundColor Cyan
