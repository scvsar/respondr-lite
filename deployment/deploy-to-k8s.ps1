#!/usr/bin/env pwsh

# Respondr Kubernetes Deployment Script
# This script deploys the Respondr application to a Kubernetes cluster

param(
    [Parameter(Mandatory=$false)]
    [string]$Namespace = "respondr",
    
    [Parameter(Mandatory=$false)]
    [string]$ImageTag = "latest",
    
    [Parameter(Mandatory=$false)]
    [string]$AzureOpenAIApiKey,
    
    [Parameter(Mandatory=$false)]
    [string]$ResourceGroupName = "respondr",
    
    [Parameter(Mandatory=$false)]
    [string]$OpenAIDeploymentName = "gpt-4o-mini",
    
    [Parameter(Mandatory=$false)]
    [string]$ApiVersion = "2025-01-01-preview",
    
    [Parameter(Mandatory=$false)]
    [switch]$SkipSecretsCreation = $false,
    
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
$templatePath = "secrets-template.yaml"

if (-not (Test-Path $secretsFile) -and -not $SkipSecretsCreation) {
    Write-Host "No secrets.yaml file found. Creating secrets..." -ForegroundColor Yellow
    
    if ($AzureOpenAIApiKey) {
        # Use provided API key directly
        Write-Host "Creating secrets file from template using provided API key..." -ForegroundColor Yellow
        (Get-Content $templatePath) -replace 'YOUR_AZURE_OPENAI_API_KEY_HERE', $AzureOpenAIApiKey | Set-Content $secretsFile
        Write-Host "Secrets file created successfully using provided API key." -ForegroundColor Green
    } else {
        # Auto-generate secrets from Azure
        Write-Host "Auto-generating secrets from Azure resources..." -ForegroundColor Yellow
        
        try {
            # Get OpenAI account name with more robust handling
            $openAIListCommand = "az cognitiveservices account list -g `"$ResourceGroupName`" --query `"[?kind=='OpenAI']`" -o json"
            $openAIAccountsJson = Invoke-Expression $openAIListCommand
            $openAIAccounts = $openAIAccountsJson | ConvertFrom-Json
            
            if (-not $openAIAccounts -or @($openAIAccounts).Count -eq 0) {
                Write-Error "No Azure OpenAI account found in resource group $ResourceGroupName"
                exit 1
            }
            
            # Take the first account if multiple are returned
            $openAIAccount = $openAIAccounts[0]
            $openAIName = $openAIAccount.name
            
            Write-Host "  Found Azure OpenAI account: $openAIName" -ForegroundColor Cyan
            
            # Get endpoint and key with more robust handling
            $endpointCommand = "az cognitiveservices account show -n `"$openAIName`" -g `"$ResourceGroupName`" --query `"properties.endpoint`" -o tsv"
            $openAIEndpoint = (Invoke-Expression $endpointCommand).Trim()
            
            $keyCommand = "az cognitiveservices account keys list -n `"$openAIName`" -g `"$ResourceGroupName`" --query `"key1`" -o tsv"
            $openAIKey = (Invoke-Expression $keyCommand).Trim()
            
            if (-not $openAIEndpoint -or -not $openAIKey) {
                Write-Error "Failed to retrieve endpoint or key for Azure OpenAI account"
                exit 1
            }
            
            # Create secrets.yaml from template
            Copy-Item -Path $templatePath -Destination $secretsFile -Force
            
            # Read the template content
            $secretsContent = Get-Content -Path $secretsFile -Raw
            
            # Replace placeholders with actual values
            $secretsContent = $secretsContent -replace 'YOUR_AZURE_OPENAI_API_KEY_HERE', $openAIKey
            $secretsContent = $secretsContent -replace 'https://westus.api.cognitive.microsoft.com/', $openAIEndpoint
            $secretsContent = $secretsContent -replace 'gpt-4o-mini', $OpenAIDeploymentName
            $secretsContent = $secretsContent -replace '2025-01-01-preview', $ApiVersion
            
            # Write the updated content
            Set-Content -Path $secretsFile -Value $secretsContent
            
            Write-Host "  Secrets file created successfully!" -ForegroundColor Green
        }
        catch {
            Write-Error "Error creating secrets file: $_"
            exit 1
        }
    }
} elseif (Test-Path $secretsFile) {
    Write-Host "Using existing secrets file: $secretsFile" -ForegroundColor Cyan
} elseif ($SkipSecretsCreation) {
    Write-Host "Skipping secrets creation as requested" -ForegroundColor Yellow
}

# Get ACR details
Write-Host "Getting Azure Container Registry details..." -ForegroundColor Yellow
$acrName = az acr list -g $ResourceGroupName --query "[0].name" -o tsv
if (-not $acrName) {
    Write-Error "No Azure Container Registry found in resource group '$ResourceGroupName'"
    exit 1
}

$acrLoginServer = az acr show --name $acrName --query loginServer -o tsv
$fullImageName = "$acrLoginServer/respondr:$ImageTag"

Write-Host "ACR Name: $acrName" -ForegroundColor Cyan
Write-Host "ACR Login Server: $acrLoginServer" -ForegroundColor Cyan
Write-Host "Using image: $fullImageName" -ForegroundColor Cyan

# Update the image in the deployment template
$deploymentFile = "respondr-k8s-template.yaml"
$tempFile = "respondr-k8s-temp.yaml"

Write-Host "Preparing deployment configuration..." -ForegroundColor Yellow
(Get-Content $deploymentFile) -replace '{{ACR_IMAGE_PLACEHOLDER}}', $fullImageName | Set-Content $tempFile

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
Write-Host "3. Send test webhook: curl -X POST http://respondr.local/webhook -H 'Content-Type: application/json' -d '{`"name`":`"Test`",`"text`":`"SAR1 ETA 15 min`",`"created_at`":1234567890}'" -ForegroundColor White
