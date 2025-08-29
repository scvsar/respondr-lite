# Setup GitHub Actions CI/CD for Azure Container Apps Deployment
# This script helps configure Azure service principal and GitHub secrets

param(
    [Parameter(Mandatory)]
    [string]$GitHubOrg,  # Your GitHub username or organization
    
    [Parameter(Mandatory)]
    [string]$GitHubRepo,  # Repository name (e.g., "respondr-lite")
    
    [Parameter(Mandatory)]
    [string]$ResourceGroup,
    
    [string]$ServicePrincipalName = "github-actions-respondr-preprod",
    [string]$Branch = "preprod",
    [switch]$UseOIDC = $true,  # Recommended: Use OIDC instead of secrets
    [switch]$ConfigureGitHub  # Also configure GitHub secrets via CLI
)

$ErrorActionPreference = "Stop"

Write-Host "🚀 Setting up GitHub Actions CI/CD" -ForegroundColor Cyan
Write-Host "Repository: $GitHubOrg/$GitHubRepo" -ForegroundColor Gray
Write-Host "Branch: $Branch" -ForegroundColor Gray
Write-Host "Resource Group: $ResourceGroup" -ForegroundColor Gray
Write-Host ""

# Check prerequisites
Write-Host "Checking prerequisites..." -ForegroundColor Yellow

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw "Azure CLI not found. Install from: https://aka.ms/installazurecli"
}

if ($ConfigureGitHub -and -not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Warning "GitHub CLI not found. Install from: https://cli.github.com/"
    Write-Host "You'll need to manually add secrets to GitHub" -ForegroundColor Yellow
    $ConfigureGitHub = $false
}

# Login to Azure if needed
Write-Host "Checking Azure login..." -ForegroundColor Yellow
$account = az account show 2>$null | ConvertFrom-Json
if (-not $account) {
    Write-Host "Not logged in to Azure. Running 'az login'..." -ForegroundColor Yellow
    az login
    $account = az account show | ConvertFrom-Json
}

Write-Host "Logged in as: $($account.user.name)" -ForegroundColor Green
Write-Host "Subscription: $($account.name) ($($account.id))" -ForegroundColor Green
Write-Host ""

$SubscriptionId = $account.id
$TenantId = $account.tenantId

# Create or get service principal
Write-Host "Setting up service principal..." -ForegroundColor Yellow

# Check if app already exists
$existingApp = az ad app list --display-name $ServicePrincipalName --query "[0]" 2>$null | ConvertFrom-Json

if ($existingApp) {
    Write-Host "App registration already exists: $ServicePrincipalName" -ForegroundColor Green
    $appId = $existingApp.appId
    
    # Check if service principal exists
    $existingSp = az ad sp show --id $appId 2>$null | ConvertFrom-Json
    if (-not $existingSp) {
        Write-Host "Creating service principal for existing app..." -ForegroundColor Yellow
        az ad sp create --id $appId | Out-Null
    }
} else {
    Write-Host "Creating new app registration: $ServicePrincipalName" -ForegroundColor Yellow
    $app = az ad app create --display-name $ServicePrincipalName | ConvertFrom-Json
    $appId = $app.appId
    
    Write-Host "Creating service principal..." -ForegroundColor Yellow
    az ad sp create --id $appId | Out-Null
}

Write-Host "Application ID: $appId" -ForegroundColor Green

# Get service principal object ID
$sp = az ad sp show --id $appId | ConvertFrom-Json
$spObjectId = $sp.id

# Assign role to resource group
Write-Host "Assigning Contributor role to resource group: $ResourceGroup" -ForegroundColor Yellow

$existingAssignment = az role assignment list `
    --assignee $appId `
    --scope "/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup" `
    --query "[?roleDefinitionName=='Contributor']" | ConvertFrom-Json

if ($existingAssignment.Count -eq 0) {
    az role assignment create `
        --assignee-object-id $spObjectId `
        --role "Contributor" `
        --scope "/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup" | Out-Null
    Write-Host "Role assignment created" -ForegroundColor Green
} else {
    Write-Host "Role assignment already exists" -ForegroundColor Green
}

# Configure authentication method
$secrets = @{}
$secrets["AZURE_CLIENT_ID"] = $appId
$secrets["AZURE_TENANT_ID"] = $TenantId
$secrets["AZURE_SUBSCRIPTION_ID"] = $SubscriptionId

if ($UseOIDC) {
    Write-Host ""
    Write-Host "Configuring OIDC federation for GitHub Actions..." -ForegroundColor Yellow
    
    $federatedCredName = "github-$Branch-deployment"
    $subject = "repo:${GitHubOrg}/${GitHubRepo}:ref:refs/heads/$Branch"
    
    # Check if federated credential exists
    $existingCreds = az ad app federated-credential list --id $appId | ConvertFrom-Json
    $existing = $existingCreds | Where-Object { $_.name -eq $federatedCredName }
    
    if (-not $existing) {
        $credentialParams = @{
            name = $federatedCredName
            issuer = "https://token.actions.githubusercontent.com"
            subject = $subject
            description = "GitHub Actions $Branch branch deployment"
            audiences = @("api://AzureADTokenExchange")
        } | ConvertTo-Json -Compress
        
        $credentialParams | az ad app federated-credential create --id $appId --parameters '@-' | Out-Null
        Write-Host "OIDC federation configured for: $subject" -ForegroundColor Green
    } else {
        Write-Host "OIDC federation already exists for: $subject" -ForegroundColor Green
    }
    
    Write-Host ""
    Write-Host "✅ OIDC authentication configured (recommended)" -ForegroundColor Green
    Write-Host "No client secret needed - using federated credentials" -ForegroundColor Gray
    
} else {
    Write-Host ""
    Write-Host "Creating client secret..." -ForegroundColor Yellow
    
    $credential = az ad app credential reset --id $appId --years 1 | ConvertFrom-Json
    $secrets["AZURE_CLIENT_SECRET"] = $credential.password
    
    Write-Host "⚠️  Client secret created (expires in 1 year)" -ForegroundColor Yellow
    Write-Host "Consider using OIDC for better security" -ForegroundColor Gray
}

# Configure GitHub secrets
Write-Host ""
Write-Host "GitHub Secrets Configuration" -ForegroundColor Cyan
Write-Host "=============================" -ForegroundColor Cyan

if ($ConfigureGitHub) {
    Write-Host "Configuring GitHub secrets via CLI..." -ForegroundColor Yellow
    
    # Check if we're in the right repo
    $currentRepo = gh repo view --json nameWithOwner 2>$null | ConvertFrom-Json
    if ($currentRepo.nameWithOwner -ne "$GitHubOrg/$GitHubRepo") {
        Write-Warning "Current directory is not the expected repository"
        Write-Host "Expected: $GitHubOrg/$GitHubRepo" -ForegroundColor Red
        Write-Host "Current: $($currentRepo.nameWithOwner)" -ForegroundColor Red
        $ConfigureGitHub = $false
    }
}

if ($ConfigureGitHub) {
    foreach ($key in $secrets.Keys) {
        Write-Host "Setting secret: $key" -ForegroundColor Gray
        $secrets[$key] | gh secret set $key
    }
    
    Write-Host ""
    Write-Host "✅ GitHub secrets configured automatically" -ForegroundColor Green
    
} else {
    Write-Host ""
    Write-Host "Add these secrets to GitHub manually:" -ForegroundColor Yellow
    Write-Host "Go to: https://github.com/$GitHubOrg/$GitHubRepo/settings/secrets/actions" -ForegroundColor Cyan
    Write-Host ""
    
    foreach ($key in $secrets.Keys) {
        Write-Host "Secret Name: $key" -ForegroundColor White
        if ($key -like "*SECRET*") {
            Write-Host "Value: [REDACTED - See above or Azure Portal]" -ForegroundColor DarkGray
        } else {
            Write-Host "Value: $($secrets[$key])" -ForegroundColor Gray
        }
        Write-Host ""
    }
}

# Docker Hub configuration reminder
Write-Host ""
Write-Host "Docker Hub Configuration" -ForegroundColor Cyan
Write-Host "========================" -ForegroundColor Cyan
Write-Host "Don't forget to add Docker Hub credentials:" -ForegroundColor Yellow
Write-Host "1. Go to: https://hub.docker.com/settings/security" -ForegroundColor Gray
Write-Host "2. Create an access token" -ForegroundColor Gray
Write-Host "3. Add to GitHub secrets:" -ForegroundColor Gray
Write-Host "   - DOCKER_USERNAME: Your Docker Hub username" -ForegroundColor White
Write-Host "   - DOCKER_TOKEN: The access token you created" -ForegroundColor White

# Summary
Write-Host ""
Write-Host "🎉 Setup Complete!" -ForegroundColor Green
Write-Host ""
Write-Host "Summary:" -ForegroundColor Cyan
Write-Host "- Service Principal: $ServicePrincipalName" -ForegroundColor White
Write-Host "- Application ID: $appId" -ForegroundColor White
Write-Host "- Resource Group: $ResourceGroup" -ForegroundColor White
Write-Host "- Authentication: $(if ($UseOIDC) { 'OIDC Federation' } else { 'Client Secret' })" -ForegroundColor White
Write-Host "- GitHub Subject: repo:${GitHubOrg}/${GitHubRepo}:ref:refs/heads/$Branch" -ForegroundColor White

Write-Host ""
Write-Host "Next Steps:" -ForegroundColor Cyan
Write-Host "1. Add Docker Hub secrets to GitHub (DOCKER_USERNAME, DOCKER_TOKEN)" -ForegroundColor Gray
Write-Host "2. Update workflow file with your Container App name" -ForegroundColor Gray
Write-Host "3. Push changes to '$Branch' branch to trigger deployment" -ForegroundColor Gray

# Output to file for reference
$outputFile = "github-actions-setup-$(Get-Date -Format 'yyyyMMdd-HHmmss').txt"
@"
GitHub Actions CI/CD Setup
==========================
Date: $(Get-Date)

Azure Configuration:
- Subscription ID: $SubscriptionId
- Tenant ID: $TenantId
- Resource Group: $ResourceGroup
- Service Principal: $ServicePrincipalName
- Application ID: $appId
- Authentication: $(if ($UseOIDC) { 'OIDC Federation' } else { 'Client Secret' })

GitHub Configuration:
- Repository: $GitHubOrg/$GitHubRepo
- Branch: $Branch
- OIDC Subject: repo:${GitHubOrg}/${GitHubRepo}:ref:refs/heads/$Branch

Required GitHub Secrets:
- AZURE_CLIENT_ID: $appId
- AZURE_TENANT_ID: $TenantId  
- AZURE_SUBSCRIPTION_ID: $SubscriptionId
$(if (-not $UseOIDC) { "- AZURE_CLIENT_SECRET: [Stored securely]" })
- DOCKER_USERNAME: [Your Docker Hub username]
- DOCKER_TOKEN: [Your Docker Hub access token]

"@ | Out-File -FilePath $outputFile

Write-Host ""
Write-Host "📄 Configuration saved to: $outputFile" -ForegroundColor Gray

<# 
Example usage:

# Basic setup with OIDC (recommended)
.\setup-github-actions.ps1 `
    -GitHubOrg "randytreit" `
    -GitHubRepo "respondr-lite" `
    -ResourceGroup "respondrlite"

# Setup with automatic GitHub secret configuration
.\setup-github-actions.ps1 `
    -GitHubOrg "randytreit" `
    -GitHubRepo "respondr-lite" `
    -ResourceGroup "respondrlite" `
    -ConfigureGitHub

# Setup with client secret instead of OIDC
.\setup-github-actions.ps1 `
    -GitHubOrg "randytreit" `
    -GitHubRepo "respondr-lite" `
    -ResourceGroup "respondrlite" `
    -UseOIDC:$false

# Setup for different branch
.\setup-github-actions.ps1 `
    -GitHubOrg "randytreit" `
    -GitHubRepo "respondr-lite" `
    -ResourceGroup "respondrlite" `
    -Branch "main"
#>