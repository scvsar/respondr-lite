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
    [string]$OpenAIDeploymentName = "gpt-4-1-nano",
    
    [Parameter(Mandatory=$false)]
    [string]$ApiVersion = "2024-12-01-preview",
    
    [Parameter(Mandatory=$false)]
    [switch]$SkipSecretsCreation = $false,
    
    [Parameter(Mandatory=$false)]
    [switch]$SkipImageBuild = $false,
    
    [Parameter(Mandatory=$false)]
    [switch]$DryRun = $false
)

Write-Host "Respondr Kubernetes Deployment Script" -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Green

# Check prerequisites
Write-Host "Checking prerequisites..." -ForegroundColor Yellow

# Check if kubectl is available
if (-not (Get-Command kubectl -ErrorAction SilentlyContinue)) {
    Write-Error "kubectl is not installed or not in PATH. Please install kubectl first."
    exit 1
}

# Check if Docker is available (only if not skipping build)
if (-not $SkipImageBuild -and -not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error "Docker is not installed or not in PATH. Please install Docker first."
    exit 1
}

# Check if Azure CLI is available
if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    Write-Error "Azure CLI is not installed or not in PATH. Please install Azure CLI first."
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
            $secretsContent = $secretsContent -replace 'gpt-4.1-mini', $OpenAIDeploymentName
            $secretsContent = $secretsContent -replace '2024-12-01-preview', $ApiVersion
            
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

# Build and push Docker image (unless skipped)
if (-not $SkipImageBuild) {
    Write-Host "Building and pushing Docker image..." -ForegroundColor Yellow
    
    # Navigate to project root (parent of deployment folder)
    $projectRoot = Split-Path $PSScriptRoot -Parent
    $originalLocation = Get-Location
    
    try {
        Set-Location $projectRoot
        Write-Host "Building from: $projectRoot" -ForegroundColor Cyan
        
        # Login to ACR
        Write-Host "Logging into ACR..." -ForegroundColor Yellow
        if (-not $DryRun) {
            az acr login --name $acrName | Out-Null
            if ($LASTEXITCODE -ne 0) {
                Write-Error "Failed to login to ACR"
                exit 1
            }
        }
        
        # Build Docker image
        Write-Host "Building Docker image..." -ForegroundColor Yellow
        if (-not $DryRun) {
            docker build -t respondr:$ImageTag -t $fullImageName .
            if ($LASTEXITCODE -ne 0) {
                Write-Error "Docker build failed"
                exit 1
            }
            Write-Host "Docker image built successfully" -ForegroundColor Green
        } else {
            Write-Host "DRY RUN: Would build Docker image" -ForegroundColor Cyan
        }
        
        # Push to ACR
        Write-Host "Pushing image to ACR..." -ForegroundColor Yellow
        if (-not $DryRun) {
            docker push $fullImageName
            if ($LASTEXITCODE -ne 0) {
                Write-Error "Docker push failed"
                exit 1
            }
            Write-Host "Image pushed to ACR successfully" -ForegroundColor Green
        } else {
            Write-Host "DRY RUN: Would push image to ACR" -ForegroundColor Cyan
        }
        
        # Verify image exists in ACR
        if (-not $DryRun) {
            Write-Host "Verifying image in ACR..." -ForegroundColor Yellow
            $repositories = az acr repository list --name $acrName -o json | ConvertFrom-Json
            if ($repositories -contains "respondr") {
                Write-Host "Image verified in ACR" -ForegroundColor Green
            } else {
                Write-Error "Image not found in ACR after push"
                exit 1
            }
        }
        
    } finally {
        Set-Location $originalLocation
    }
} else {
    Write-Host "Skipping Docker image build (using existing image)" -ForegroundColor Yellow
    
    # Verify image exists in ACR if not building
    if (-not $DryRun) {
        Write-Host "Verifying existing image in ACR..." -ForegroundColor Yellow
        $repositories = az acr repository list --name $acrName -o json | ConvertFrom-Json
        if ($repositories -notcontains "respondr") {
            Write-Error "Image 'respondr' not found in ACR. Please build the image first or remove -SkipImageBuild flag."
            exit 1
        }
        Write-Host "Existing image verified in ACR" -ForegroundColor Green
    }
}

# Update the image and identity details in the deployment template
$deploymentFile = "respondr-k8s-template.yaml"
$tempFile = "respondr-k8s-temp.yaml"

Write-Host "Preparing deployment configuration..." -ForegroundColor Yellow

# Get deployment outputs for identity configuration
Write-Host "Getting identity configuration from Azure deployment..." -ForegroundColor Yellow
$deploy = az deployment group show --resource-group $ResourceGroupName --name main -o json | ConvertFrom-Json
$podIdentityClientId = $deploy.properties.outputs.podIdentityClientId.value
$tenantId = az account show --query tenantId -o tsv

# Get DNS zone for hostname configuration
$hostname = "respondr.paincave.pro"  # Use actual domain
Write-Host "Using hostname: $hostname" -ForegroundColor Green

# Replace placeholders in the template
(Get-Content $deploymentFile) `
    -replace '{{ACR_IMAGE_PLACEHOLDER}}', $fullImageName `
    -replace 'CLIENT_ID_PLACEHOLDER', $podIdentityClientId `
    -replace 'TENANT_ID_PLACEHOLDER', $tenantId `
    -replace 'HOSTNAME_PLACEHOLDER', $hostname | Set-Content $tempFile

Write-Host "Configuration prepared:" -ForegroundColor Green
Write-Host "  Image: $fullImageName" -ForegroundColor Cyan
Write-Host "  Client ID: $podIdentityClientId" -ForegroundColor Cyan
Write-Host "  Tenant ID: $tenantId" -ForegroundColor Cyan
Write-Host "  Hostname: $hostname" -ForegroundColor Cyan

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
        Write-Host "- Ingress Host: $hostname" -ForegroundColor Cyan
        Write-Host "- API Endpoint: https://$hostname/api/responders" -ForegroundColor Cyan
        Write-Host "- Webhook Endpoint: https://$hostname/webhook" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "Authentication:" -ForegroundColor Green
        Write-Host "- Entra (Azure AD) authentication is configured via Application Gateway" -ForegroundColor Cyan
        Write-Host "- Workload Identity is configured for Azure resource access" -ForegroundColor Cyan
        Write-Host "- All traffic will be authenticated via Microsoft Entra" -ForegroundColor Cyan        
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
Write-Host "Summary of actions performed:" -ForegroundColor Yellow
if (-not $SkipImageBuild) {
    Write-Host "✅ Built Docker image: respondr:$ImageTag" -ForegroundColor Green
    Write-Host "✅ Pushed image to ACR: $fullImageName" -ForegroundColor Green
} else {
    Write-Host "Skipped Docker image build (used existing)" -ForegroundColor Yellow
}
Write-Host "✅ Created/updated Kubernetes secrets" -ForegroundColor Green
Write-Host "✅ Deployed application to Kubernetes" -ForegroundColor Green
Write-Host "✅ Created namespace: $Namespace" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "1. Verify DNS configuration points to Application Gateway IP" -ForegroundColor White
Write-Host "2. Test authentication: Navigate to https://$hostname in browser" -ForegroundColor White
Write-Host "3. Test API endpoint: https://$hostname/api/responders (after authentication)" -ForegroundColor White
Write-Host "4. Send test webhook: Use authenticated endpoint for webhook testing" -ForegroundColor White
Write-Host ""
Write-Host "Security Features Enabled:" -ForegroundColor Green
Write-Host "✅ Microsoft Entra (Azure AD) authentication via Application Gateway" -ForegroundColor Green
Write-Host "✅ Azure Workload Identity for secure access to Azure resources" -ForegroundColor Green
Write-Host "✅ TLS/SSL termination at Application Gateway" -ForegroundColor Green
Write-Host "✅ Dedicated namespace isolation" -ForegroundColor Green
