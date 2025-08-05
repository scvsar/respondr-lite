# Enhanced Deployment Script for Respondr - Unified Template with OAuth2 Options
# Usage:
#   ./deploy-unified.ps1                    # Deploy with OAuth2 (default)
#   ./deploy-unified.ps1 -NoOAuth2          # Deploy without OAuth2
#   ./deploy-unified.ps1 -NoOAuth2 -Force   # Force deployment without OAuth2

param(
    [switch]$NoOAuth2,
    [switch]$Force,
    [switch]$Help
)

if ($Help) {
    Write-Host "Enhanced Respondr Deployment Script - Unified Template" -ForegroundColor Green
    Write-Host ""
    Write-Host "Usage:" -ForegroundColor Yellow
    Write-Host "  ./deploy-unified.ps1                    # Deploy with OAuth2 (default)" -ForegroundColor White
    Write-Host "  ./deploy-unified.ps1 -NoOAuth2          # Deploy without OAuth2" -ForegroundColor White
    Write-Host "  ./deploy-unified.ps1 -NoOAuth2 -Force   # Force deployment without OAuth2" -ForegroundColor White
    Write-Host ""
    Write-Host "Options:" -ForegroundColor Yellow
    Write-Host "  -NoOAuth2   : Deploy without OAuth2 authentication (direct access)" -ForegroundColor White
    Write-Host "  -Force      : Skip confirmation prompts" -ForegroundColor White
    Write-Host "  -Help       : Show this help message" -ForegroundColor White
    Write-Host ""
    Write-Host "OAuth2 vs Direct Access:" -ForegroundColor Yellow
    Write-Host "  OAuth2      : Secure Azure AD authentication, enterprise ready" -ForegroundColor Green
    Write-Host "  Direct      : Simple direct access, development/testing friendly" -ForegroundColor Cyan
    exit 0
}

Write-Host "🚀 Respondr Unified Deployment Script" -ForegroundColor Green
Write-Host "=====================================`n" -ForegroundColor Green

# Determine deployment mode
$deploymentMode = if ($NoOAuth2) { "Direct Access" } else { "OAuth2 Protected" }
$modeColor = if ($NoOAuth2) { "Cyan" } else { "Green" }

Write-Host "📋 Deployment Configuration:" -ForegroundColor Yellow
Write-Host "   Mode: $deploymentMode" -ForegroundColor $modeColor
Write-Host "   Template: respondr-k8s-unified-template.yaml" -ForegroundColor White
Write-Host ""

# Confirmation prompt (unless Force is specified)
if (-not $Force) {
    if ($NoOAuth2) {
        Write-Host "⚠️  WARNING: Deploying without OAuth2 authentication!" -ForegroundColor Red
        Write-Host "   This provides direct access to the application without Azure AD protection." -ForegroundColor Yellow
        Write-Host "   Recommended for development/testing environments only." -ForegroundColor Yellow
        Write-Host ""
    } else {
        Write-Host "🔐 Deploying with OAuth2 authentication (Azure AD)" -ForegroundColor Green
        Write-Host "   This provides enterprise-grade security for production use." -ForegroundColor White
        Write-Host ""
    }
    
    $confirm = Read-Host "Continue with $deploymentMode deployment? (y/N)"
    if ($confirm -ne 'y' -and $confirm -ne 'Y') {
        Write-Host "❌ Deployment cancelled by user" -ForegroundColor Red
        exit 1
    }
}

Write-Host "🔧 Starting deployment process..." -ForegroundColor Blue
Write-Host ""

# Check prerequisites
Write-Host "📋 Checking prerequisites..." -ForegroundColor Yellow

# Check if kubectl is available
try {
    kubectl version --client --short | Out-Null
    Write-Host "   ✅ kubectl available" -ForegroundColor Green
} catch {
    Write-Host "   ❌ kubectl not found. Please install kubectl first." -ForegroundColor Red
    exit 1
}

# Check if connected to cluster
try {
    $context = kubectl config current-context 2>$null
    Write-Host "   ✅ Connected to cluster: $context" -ForegroundColor Green
} catch {
    Write-Host "   ❌ Not connected to Kubernetes cluster" -ForegroundColor Red
    exit 1
}

# Check if secrets exist
Write-Host ""
Write-Host "🔐 Checking secrets..." -ForegroundColor Yellow

$secretsExist = $true

# Check respondr-secrets
try {
    kubectl get secret respondr-secrets -n respondr 2>$null | Out-Null
    Write-Host "   ✅ respondr-secrets found" -ForegroundColor Green
} catch {
    Write-Host "   ❌ respondr-secrets not found" -ForegroundColor Red
    $secretsExist = $false
}

# Check oauth2-secrets only if OAuth2 is enabled
if (-not $NoOAuth2) {
    try {
        kubectl get secret oauth2-secrets -n respondr 2>$null | Out-Null
        Write-Host "   ✅ oauth2-secrets found" -ForegroundColor Green
    } catch {
        Write-Host "   ❌ oauth2-secrets not found" -ForegroundColor Red
        $secretsExist = $false
    }
}

if (-not $secretsExist) {
    Write-Host ""
    Write-Host "❌ Required secrets missing. Please run create-secrets.ps1 first." -ForegroundColor Red
    exit 1
}

# Load configuration from .env file
Write-Host ""
Write-Host "📁 Loading configuration..." -ForegroundColor Yellow

$envFile = ".\backend\.env"
if (-not (Test-Path $envFile)) {
    Write-Host "   ❌ .env file not found. Please run create-secrets.ps1 first." -ForegroundColor Red
    exit 1
}

$config = @{}
Get-Content $envFile | ForEach-Object {
    if ($_ -match '^([^#].*)=(.*)$') {
        $config[$matches[1]] = $matches[2]
    }
}

$requiredVars = @('ACR_IMAGE', 'HOSTNAME', 'TENANT_ID', 'CLIENT_ID')
$missingVars = @()

foreach ($var in $requiredVars) {
    if (-not $config[$var]) {
        $missingVars += $var
    } else {
        Write-Host "   ✅ $var loaded" -ForegroundColor Green
    }
}

if ($missingVars.Count -gt 0) {
    Write-Host "   ❌ Missing variables: $($missingVars -join ', ')" -ForegroundColor Red
    exit 1
}

# Process the unified template
Write-Host ""
Write-Host "📝 Processing deployment template..." -ForegroundColor Yellow

$templateFile = ".\respondr-k8s-unified-template.yaml"
if (-not (Test-Path $templateFile)) {
    Write-Host "   ❌ Template file not found: $templateFile" -ForegroundColor Red
    exit 1
}

$template = Get-Content $templateFile -Raw

# Replace placeholders
$template = $template -replace '{{ACR_IMAGE_PLACEHOLDER}}', $config['ACR_IMAGE']
$template = $template -replace '{{HOSTNAME_PLACEHOLDER}}', $config['HOSTNAME']
$template = $template -replace '{{TENANT_ID_PLACEHOLDER}}', $config['TENANT_ID']
$template = $template -replace '{{CLIENT_ID_PLACEHOLDER}}', $config['CLIENT_ID']

# Configure OAuth2 containers and service ports
if ($NoOAuth2) {
    Write-Host "   🔧 Configuring for direct access (no OAuth2)" -ForegroundColor Cyan
    
    # Remove OAuth2 container section
    $template = $template -replace '(?s){{OAUTH2_CONTAINER_START}}.*?{{OAUTH2_CONTAINER_END}}', ''
    
    # Configure service to point directly to main container
    $servicePortConfig = @"
  - name: http
    port: 80
    targetPort: 8000
    protocol: TCP
"@
    
} else {
    Write-Host "   🔐 Configuring for OAuth2 authentication" -ForegroundColor Green
    
    # Keep OAuth2 container section (remove markers)
    $template = $template -replace '{{OAUTH2_CONTAINER_START}}', ''
    $template = $template -replace '{{OAUTH2_CONTAINER_END}}', ''
    
    # Configure service to point to OAuth2 proxy
    $servicePortConfig = @"
  - name: http
    port: 80
    targetPort: 4180
    protocol: TCP
"@
}

# Replace service port configuration
$template = $template -replace '{{SERVICE_PORT_CONFIG}}', $servicePortConfig

# Write processed template
$outputFile = ".\respondr-k8s-processed.yaml"
$template | Out-File -FilePath $outputFile -Encoding UTF8

Write-Host "   ✅ Template processed and saved to: $outputFile" -ForegroundColor Green

# Deploy to Kubernetes
Write-Host ""
Write-Host "🚀 Deploying to Kubernetes..." -ForegroundColor Blue

try {
    kubectl apply -f $outputFile
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "   ✅ Deployment successful!" -ForegroundColor Green
    } else {
        Write-Host "   ❌ Deployment failed" -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "   ❌ Deployment error: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# Wait for deployment rollout
Write-Host ""
Write-Host "⏳ Waiting for deployment rollout..." -ForegroundColor Yellow

try {
    kubectl rollout status deployment/respondr-deployment -n respondr --timeout=300s
    Write-Host "   ✅ Rollout completed successfully" -ForegroundColor Green
} catch {
    Write-Host "   ⚠️  Rollout status check failed, but deployment may still be progressing" -ForegroundColor Yellow
}

# Display deployment information
Write-Host ""
Write-Host "📊 Deployment Summary" -ForegroundColor Green
Write-Host "===================" -ForegroundColor Green

Write-Host "Mode: $deploymentMode" -ForegroundColor $modeColor
Write-Host "URL: https://$($config['HOSTNAME'])" -ForegroundColor White

if ($NoOAuth2) {
    Write-Host ""
    Write-Host "🔓 Direct Access Configuration:" -ForegroundColor Cyan
    Write-Host "   • No authentication required" -ForegroundColor White
    Write-Host "   • Direct access to FastAPI application" -ForegroundColor White
    Write-Host "   • Webhook endpoint: /webhook" -ForegroundColor White
    Write-Host "   • API endpoint: /api/responders" -ForegroundColor White
} else {
    Write-Host ""
    Write-Host "🔐 OAuth2 Configuration:" -ForegroundColor Green
    Write-Host "   • Azure AD authentication required" -ForegroundColor White
    Write-Host "   • Webhook endpoint bypasses authentication" -ForegroundColor White
    Write-Host "   • Dashboard/API requires Azure AD login" -ForegroundColor White
}

Write-Host ""
Write-Host "🔍 Next Steps:" -ForegroundColor Yellow
Write-Host "   1. Check deployment: kubectl get pods -n respondr" -ForegroundColor White
Write-Host "   2. View logs: kubectl logs -n respondr -l app=respondr" -ForegroundColor White
Write-Host "   3. Test application: https://$($config['HOSTNAME'])" -ForegroundColor White

if ($NoOAuth2) {
    Write-Host "   4. Test webhook: python backend/test_webhook.py --production" -ForegroundColor White
} else {
    Write-Host "   4. Test webhook: python backend/test_webhook.py --production" -ForegroundColor White
    Write-Host "   5. Access dashboard: Sign in with Azure AD credentials" -ForegroundColor White
}

Write-Host ""
Write-Host "🎉 Deployment completed successfully!" -ForegroundColor Green

# Clean up processed file
Remove-Item $outputFile -Force -ErrorAction SilentlyContinue
