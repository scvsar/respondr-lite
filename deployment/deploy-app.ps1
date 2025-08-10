param(
    [Parameter(Mandatory=$true)]
    [string]$ResourceGroupName,

    [Parameter(Mandatory=$true)]
    [string]$Domain,

    [Parameter(Mandatory=$false)]
    [string]$Namespace = "respondr",

    [switch]$SkipImageBuild
)

Write-Host "Respondr App Deployment (App-only)" -ForegroundColor Green
Write-Host "==================================" -ForegroundColor Green
Write-Host "Resource Group: $ResourceGroupName" -ForegroundColor Cyan
Write-Host "Domain: $Domain" -ForegroundColor Cyan
Write-Host "Namespace: $Namespace" -ForegroundColor Cyan

# Generate values
& (Join-Path $PSScriptRoot 'generate-values.ps1') -ResourceGroupName $ResourceGroupName -Domain $Domain
if ($LASTEXITCODE -ne 0) { Write-Error "Failed to generate values"; exit 1 }

# Setup OAuth2 secrets (idempotent)
& (Join-Path $PSScriptRoot 'setup-oauth2.ps1') -ResourceGroupName $ResourceGroupName -Domain $Domain
if ($LASTEXITCODE -ne 0) { Write-Error "Failed to setup OAuth2"; exit 1 }

# Create application secrets (idempotent)
& (Join-Path $PSScriptRoot 'create-secrets.ps1') -ResourceGroupName $ResourceGroupName -Namespace $Namespace
if ($LASTEXITCODE -ne 0) { Write-Error "Failed to create secrets"; exit 1 }

# Apply secrets to the cluster and ensure pods pick up changes
$secretsPath = Join-Path $PSScriptRoot 'secrets.yaml'
if (Test-Path $secretsPath) {
    Write-Host "Applying Kubernetes secrets to namespace '$Namespace'..." -ForegroundColor Yellow
    kubectl apply -f $secretsPath -n $Namespace | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Error "Failed to apply secrets.yaml"; exit 1 }
    # Force a rollout so updated env vars take effect on pods
    Write-Host "Triggering rollout restart to pick up new secrets..." -ForegroundColor Yellow
    kubectl rollout restart deployment/respondr-deployment -n $Namespace | Out-Null
}

# Optionally build and push image via deploy-complete (kept simple here, prefer redeploy.ps1 for builds)
if ($SkipImageBuild) {
    Write-Host "Skipping image build (use redeploy.ps1 -Action build for new images)" -ForegroundColor Yellow
}

# Process template
& (Join-Path $PSScriptRoot 'process-template.ps1') -TemplateFile 'respondr-k8s-unified-template.yaml' -OutputFile 'respondr-k8s-generated.yaml'
if ($LASTEXITCODE -ne 0) { Write-Error "Template processing failed"; exit 1 }

# Deploy Redis
kubectl apply -f (Join-Path $PSScriptRoot 'redis-deployment.yaml') -n $Namespace
if ($LASTEXITCODE -ne 0) { Write-Error "Failed to deploy Redis"; exit 1 }

# Deploy app
kubectl apply -f (Join-Path $PSScriptRoot 'respondr-k8s-generated.yaml') -n $Namespace
if ($LASTEXITCODE -ne 0) { Write-Error "Failed to deploy application"; exit 1 }

# Wait for rollout
kubectl rollout status deployment/respondr-deployment -n $Namespace --timeout=300s

Write-Host "\nApp-only deployment completed" -ForegroundColor Green
