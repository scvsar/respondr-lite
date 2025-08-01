#!/usr/bin/env pwsh

# Respondr Kubernetes Deployment Script
# This script deploys the Respondr application to a Kubernetes cluster

param(
    [Parameter(Mandatory=$false)]
    [string]$Namespace = "default",
    
    [Parameter(Mandatory=$false)]
    [string]$ImageTag = "latest",
    
    [Parameter(Mandatory=$false)]
    [string]$AzureOpenAIApiKey,
    
    [Parameter(Mandatory=$false)]
    [switch]$DryRun = $false
)

Write-Host "Respondr Kubernetes Deployment Script" -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Green

# Check if kubectl is available
if (-not (Get-Command kubectl -ErrorAction SilentlyContinue)) {
    Write-Error "kubectl is not installed or not in PATH. Please install kubectl first."
    exit 1
}

# Check if we can connect to the cluster
Write-Host "Checking Kubernetes cluster connection..." -ForegroundColor Yellow
try {
    kubectl cluster-info --request-timeout=5s | Out-Null
    Write-Host "Connected to Kubernetes cluster" -ForegroundColor Green
} catch {
    Write-Error "Cannot connect to Kubernetes cluster. Please check your kubeconfig."
    exit 1
}

# Create namespace if it doesn't exist
if ($Namespace -ne "default") {
    Write-Host "Creating namespace '$Namespace'..." -ForegroundColor Yellow
    if (-not $DryRun) {
        kubectl create namespace $Namespace --dry-run=client -o yaml | kubectl apply -f -
    } else {
        Write-Host "DRY RUN: Would create namespace '$Namespace'" -ForegroundColor Cyan
    }
}

# Check for secrets file
$secretsFile = "secrets.yaml"
if (-not (Test-Path $secretsFile)) {
    if ($AzureOpenAIApiKey) {
        Write-Host "Creating secrets file from template..." -ForegroundColor Yellow
        (Get-Content "secrets-template.yaml") -replace 'YOUR_AZURE_OPENAI_API_KEY_HERE', $AzureOpenAIApiKey | Set-Content $secretsFile
    } else {
        Write-Host "No secrets.yaml file found and no API key provided!" -ForegroundColor Red
        Write-Host "Please either:" -ForegroundColor Yellow
        Write-Host "  1. Copy secrets-template.yaml to secrets.yaml and fill in your values" -ForegroundColor White
        Write-Host "  2. Provide -AzureOpenAIApiKey parameter" -ForegroundColor White
        exit 1
    }
}

# Update the image tag in the deployment template
$deploymentFile = "respondr-k8s-template.yaml"
$tempFile = "respondr-k8s-temp.yaml"

Write-Host "Preparing deployment configuration..." -ForegroundColor Yellow
(Get-Content $deploymentFile) -replace 'image: respondr:latest', "image: respondr:$ImageTag" | Set-Content $tempFile

# Deploy secrets first
Write-Host "Deploying secrets..." -ForegroundColor Yellow
if (-not $DryRun) {
    kubectl apply -f $secretsFile -n $Namespace
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to deploy secrets!"
        exit 1
    }
}

# Deploy to Kubernetes
Write-Host "Deploying application..." -ForegroundColor Yellow
if (-not $DryRun) {
    kubectl apply -f $tempFile -n $Namespace
      if ($LASTEXITCODE -eq 0) {
        Write-Host "Deployment successful!" -ForegroundColor Green
        
        # Wait for deployment to be ready
        Write-Host "Waiting for deployment to be ready..." -ForegroundColor Yellow
        kubectl wait --for=condition=available --timeout=300s deployment/respondr-deployment -n $Namespace
        
        # Show deployment status
        Write-Host "Deployment Status:" -ForegroundColor Green
        kubectl get pods -l app=respondr -n $Namespace
        kubectl get services -l app=respondr -n $Namespace
        kubectl get ingress respondr-ingress -n $Namespace
        
        Write-Host ""
        Write-Host "Access Information:" -ForegroundColor Green
        Write-Host "- Internal Service: respondr-service.$Namespace.svc.cluster.local" -ForegroundColor Cyan
        Write-Host "- Ingress Host: respondr.local (add to /etc/hosts or DNS)" -ForegroundColor Cyan
        Write-Host "- API Endpoint: http://respondr.local/api/responders" -ForegroundColor Cyan
        Write-Host "- Webhook Endpoint: http://respondr.local/webhook" -ForegroundColor Cyan        
    } else {
        Write-Error "Deployment failed!"
        exit 1
    }
} else {
    Write-Host "DRY RUN: Would deploy the following configuration:" -ForegroundColor Cyan
    Get-Content $tempFile
}

# Clean up temp file
Remove-Item $tempFile -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "Deployment script completed!" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "1. Update your /etc/hosts file: echo '127.0.0.1 respondr.local' >> /etc/hosts" -ForegroundColor White
Write-Host "2. Test the application: curl http://respondr.local/api/responders" -ForegroundColor White
Write-Host "3. Send test webhook: curl -X POST http://respondr.local/webhook -H 'Content-Type: application/json' -d '{\"name\":\"Test\",\"text\":\"SAR1 ETA 15 min\",\"created_at\":$(date +%s)}'" -ForegroundColor White
