#!/usr/bin/env pwsh
# migrate-to-static-web-app.ps1
# Helper script for migrating from full-stack container to Static Web App + Container App

param(
    [string]$ResourceGroup = "respondrlite",
    [string]$GitHubRepo = "", # e.g., "yourusername/respondr-lite"
    [string]$GitHubToken = "",
    [switch]$WhatIf = $false
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host "`n==== $Message ====" -ForegroundColor Cyan
}

function Write-Success {
    param([string]$Message)
    Write-Host "✅ $Message" -ForegroundColor Green
}

function Write-Warning {
    param([string]$Message)
    Write-Host "⚠️  $Message" -ForegroundColor Yellow
}

function Write-Error {
    param([string]$Message)
    Write-Host "❌ $Message" -ForegroundColor Red
}

Write-Step "Static Web App Migration Helper"

if ($WhatIf) {
    Write-Warning "Running in WhatIf mode - no changes will be made"
}

# Check prerequisites
Write-Step "Checking Prerequisites"

# Check if Azure CLI is installed
try {
    $azVersion = az version --output tsv 2>$null
    Write-Success "Azure CLI found: $($azVersion)"
} catch {
    Write-Error "Azure CLI not found. Please install Azure CLI first."
    exit 1
}

# Check if logged into Azure
try {
    $account = az account show --output json 2>$null | ConvertFrom-Json
    Write-Success "Logged into Azure as: $($account.user.name)"
} catch {
    Write-Error "Not logged into Azure. Run 'az login' first."
    exit 1
}

# Check for GitHub repo parameter
if ([string]::IsNullOrEmpty($GitHubRepo)) {
    Write-Error "GitHubRepo parameter is required (e.g., 'yourusername/respondr-lite')"
    exit 1
}

# Check if resource group exists
try {
    $rg = az group show --name $ResourceGroup --output json 2>$null | ConvertFrom-Json
    Write-Success "Resource group found: $($rg.name) in $($rg.location)"
} catch {
    Write-Error "Resource group '$ResourceGroup' not found"
    exit 1
}

Write-Step "Migration Steps Overview"
Write-Host @"
This script will help you migrate from a full-stack container to:
1. 🌐 Frontend: Azure Static Web App (Free tier)
2. 🔧 Backend: Azure Container App (existing)

Steps that will be performed:
1. Build and push backend-only Docker image
2. Deploy Static Web App resource
3. Update Container App configuration for CORS
4. Set up GitHub Actions for automatic deployments
5. Configure API communication between frontend and backend

"@

if ($WhatIf) {
    Write-Host "WhatIf mode - would execute the above steps" -ForegroundColor Yellow
    exit 0
}

$proceed = Read-Host "Do you want to proceed? (y/N)"
if ($proceed -ne "y" -and $proceed -ne "Y") {
    Write-Host "Migration cancelled."
    exit 0
}

Write-Step "Step 1: Building Backend-Only Docker Image"

# Check if backend Dockerfile exists
if (-not (Test-Path "Dockerfile.backend")) {
    Write-Error "Dockerfile.backend not found. Please create it first or run this script from the repository root."
    exit 1
}

# Build backend image
$timestamp = Get-Date -Format "yyyyMMddHHmm"
$imageName = "respondr-backend:$timestamp"

Write-Host "Building Docker image: $imageName"
docker build -f Dockerfile.backend -t $imageName .

if ($LASTEXITCODE -ne 0) {
    Write-Error "Docker build failed"
    exit 1
}

Write-Success "Backend Docker image built successfully"

Write-Step "Step 2: Deploying Infrastructure Updates"

# Get existing deployment names
$deployNamesFile = "deployment/deploy-names.json"
if (Test-Path $deployNamesFile) {
    $deployNames = Get-Content $deployNamesFile | ConvertFrom-Json
    Write-Host "Using existing deployment names:"
    $deployNames | ConvertTo-Json -Depth 2
} else {
    Write-Warning "deploy-names.json not found. You may need to run deploy-from-scratch.ps1 first."
}

Write-Step "Step 3: Manual Steps Required"

Write-Host @"
🔧 Manual steps you need to complete:

1. Push the backend Docker image to your container registry:
   docker tag $imageName your-registry.azurecr.io/respondr-backend:latest
   docker push your-registry.azurecr.io/respondr-backend:latest

2. Update your Container App to use the new backend-only image

3. Deploy the Static Web App using the Bicep template:
   - Set StaticWebAppName parameter
   - Set RepositoryUrl to: https://github.com/$GitHubRepo
   - Set GitHubToken if deploying via Bicep

4. Configure GitHub repository secrets:
   - AZURE_STATIC_WEB_APPS_API_TOKEN (from Static Web App deployment)

5. Set GitHub repository variables:
   - REACT_APP_API_URL (your Container App URL)

6. Update your DNS/domain configuration if needed

7. Test the separated deployment

"@

Write-Step "Next Steps"
Write-Host @"
After completing the manual steps above:

1. Push your code changes to trigger the GitHub Actions deployment
2. Verify the Static Web App builds and deploys correctly
3. Test API communication between frontend and backend
4. Update your monitoring and logging configurations
5. Consider removing the old full-stack deployment

For troubleshooting, check:
- GitHub Actions logs for frontend deployment
- Container App logs for backend issues
- Browser developer tools for CORS or API connectivity issues

"@

Write-Success "Migration helper completed. Please complete the manual steps above."