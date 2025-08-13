#!/usr/bin/env pwsh

# Respondr Kubernetes Deployment Script
# This script deploys the Respondr application to a Kubernetes cluster
# 
# ⚠️ DEPRECATED: This script is being phased out in favor of the template-based deployment system.
# Please use deploy-template-based.ps1 or deploy-complete.ps1 for new deployments.
# 
# For tenant-portable deployments, use the template system which automatically generates
# environment-specific configuration files that are never committed to git.

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
    [string]$OpenAIDeploymentName = "gpt-4.1-nano",
    
    [Parameter(Mandatory=$false)]
    [string]$ApiVersion = "2024-12-01-preview",
    
    [Parameter(Mandatory=$false)]
    [switch]$SkipSecretsCreation = $false,
    
    [Parameter(Mandatory=$false)]
    [switch]$SkipImageBuild = $false,
    
    [Parameter(Mandatory=$false)]
    [switch]$UseOAuth2 = $false,
    
    [Parameter(Mandatory=$false)]
    [switch]$DryRun = $false
)
# Load hostname from values.yaml if available for output info
$hostname = $null
try {
    if (Test-Path (Join-Path $PSScriptRoot 'values.yaml')) {
        $valsRaw = Get-Content (Join-Path $PSScriptRoot 'values.yaml') -Raw
        $hnMatch = $valsRaw | Select-String 'hostname: "([^"]+)"'
        if ($hnMatch) { $hostname = $hnMatch.Matches[0].Groups[1].Value }
    }
} catch {}
$hostname = $hostname -or "respondr.$ResourceGroupName"

Write-Host "⚠️ DEPRECATION WARNING ⚠️" -ForegroundColor Red
Write-Host "This deploy-to-k8s.ps1 script is deprecated and will be removed in a future version." -ForegroundColor Yellow
Write-Host "Please use one of the following modern deployment methods:" -ForegroundColor Yellow
Write-Host "  • deploy-complete.ps1    - Full end-to-end deployment with templating" -ForegroundColor Cyan
Write-Host "  • deploy-template-based.ps1 - Template-based deployment only" -ForegroundColor Cyan
Write-Host "" -ForegroundColor Yellow
Write-Host "These scripts provide:" -ForegroundColor Yellow
Write-Host "  ✅ Tenant-portable deployments" -ForegroundColor Green
Write-Host "  ✅ Environment-specific configuration generation" -ForegroundColor Green
Write-Host "  ✅ No hardcoded values in deployment files" -ForegroundColor Green
Write-Host "  ✅ Generated files that are never committed to git" -ForegroundColor Green
Write-Host ""
Write-Host "Continuing with legacy deployment..." -ForegroundColor Yellow
Write-Host ""

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
# Select deployment template based on OAuth2 setting
if ($UseOAuth2) {
    # Try multiple possible deployment files for OAuth2
    $possibleFiles = @(
        "respondr-k8s-generated.yaml",
        "respondr-k8s-current.yaml"
    )
    
    $deploymentFile = $null
    foreach ($file in $possibleFiles) {
        if (Test-Path $file) {
            $deploymentFile = $file
            break
        }
    }
    
    if (-not $deploymentFile) {
        Write-Error @"
No generated deployment file found.

Expected: respondr-k8s-generated.yaml (created by process-template.ps1)

RECOMMENDED: Run deploy-complete.ps1 or deploy-template-based.ps1 first to generate it.
"@
        exit 1
    }
    
    Write-Host "Using OAuth2 deployment file: $deploymentFile" -ForegroundColor Green
    $tempFile = $deploymentFile  # Use the found file directly
} else {
    Write-Error "Non-OAuth2 deployment is no longer supported. Please use -UseOAuth2 flag."
    exit 1
}

Write-Host "Preparing deployment configuration..." -ForegroundColor Yellow

# For OAuth2 deployment, the file already contains all necessary configuration
Write-Host "Using generated unified deployment file" -ForegroundColor Green
Write-Host "  Image: Will be updated to $fullImageName" -ForegroundColor Cyan
Write-Host "  Authentication: OAuth2 Proxy with Azure AD" -ForegroundColor Cyan
Write-Host "  Storage: Redis for shared data" -ForegroundColor Cyan

# Set temp file name first
$tempFile = "respondr-k8s-current.yaml"

# Update the image in the deployment file
Write-Host "Updating image in deployment configuration..." -ForegroundColor Yellow
(Get-Content $deploymentFile) -replace 'respondrbt774d4d55kswacr\.azurecr\.io/respondr:[^"]*', $fullImageName | Set-Content $tempFile

# Deploy secrets first
Write-Host "Deploying secrets..." -ForegroundColor Yellow
if (-not $DryRun) {
    kubectl apply -f $secretsFile -n $Namespace
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to deploy secrets!"
        exit 1
    }
    # Verify secret exists (defensive)
    if (-not (kubectl get secret respondr-secrets -n $Namespace -o name 2>$null)) {
        Write-Error "Secret 'respondr-secrets' not found in namespace '$Namespace' after apply"
        exit 1
    }
    Write-Host "✅ Secret 'respondr-secrets' confirmed in namespace '$Namespace'" -ForegroundColor Green
}

# Deploy Redis (required for shared storage)
Write-Host "Deploying Redis for shared storage..." -ForegroundColor Yellow
if (-not $DryRun) {
    kubectl apply -f "redis-deployment.yaml" -n $Namespace
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to deploy Redis!"
        exit 1
    }
    
    # Wait for Redis to be ready
    Write-Host "Waiting for Redis to be ready..." -ForegroundColor Yellow
    kubectl wait --for=condition=available --timeout=120s deployment/redis -n $Namespace
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Redis deployment may not be fully ready, continuing..."
    } else {
        Write-Host "Redis deployment is ready" -ForegroundColor Green
    }
}

# Deploy to Kubernetes
Write-Host "Deploying application..." -ForegroundColor Yellow
if (-not $DryRun) {
    # Preflight: ensure secret still exists before deploying
    if (-not (kubectl get secret respondr-secrets -n $Namespace -o name 2>$null)) {
        Write-Error "Blocking deployment: required secret 'respondr-secrets' missing in namespace '$Namespace'"
        exit 1
    }
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
        
        # Wait for and monitor Let's Encrypt certificate
        Write-Host "`nWaiting for Let's Encrypt certificate to be issued..." -ForegroundColor Yellow
        Write-Host "This may take 2-10 minutes depending on DNS propagation and Let's Encrypt processing time." -ForegroundColor Cyan
        
        $certificateTimeout = (Get-Date).AddMinutes(10)
        $certificateReady = $false
        
        do {
            Start-Sleep -Seconds 30
            $certStatus = kubectl get certificate respondr-tls-letsencrypt -n $Namespace -o jsonpath="{.status.conditions[?(@.type=='Ready')].status}" 2>$null
            
            if ($certStatus -eq "True") {
                $certificateReady = $true
                Write-Host "✅ Let's Encrypt certificate issued successfully!" -ForegroundColor Green
                break
            } else {
                # Show current certificate status
                $certInfo = kubectl get certificate respondr-tls-letsencrypt -n $Namespace -o json 2>$null | ConvertFrom-Json
                if ($certInfo) {
                    $conditions = $certInfo.status.conditions
                    $readyCondition = $conditions | Where-Object { $_.type -eq "Ready" }
                    if ($readyCondition) {
                        Write-Host "Certificate status: $($readyCondition.status) - $($readyCondition.message)" -ForegroundColor Cyan
                    } else {
                        Write-Host "Certificate is being processed..." -ForegroundColor Cyan
                    }
                } else {
                    Write-Host "Certificate resource not found, may still be initializing..." -ForegroundColor Yellow
                }
            }
        } while ((Get-Date) -lt $certificateTimeout -and -not $certificateReady)
        
        if (-not $certificateReady) {
            Write-Host "⚠️  Certificate not ready within timeout. Check status manually:" -ForegroundColor Yellow
            Write-Host "  kubectl get certificate respondr-tls-letsencrypt -n $Namespace" -ForegroundColor White
            Write-Host "  kubectl describe certificate respondr-tls-letsencrypt -n $Namespace" -ForegroundColor White
            Write-Host "  kubectl get certificaterequests -n $Namespace" -ForegroundColor White
        }
        
        Write-Host ""
        Write-Host "Access Information:" -ForegroundColor Green
        Write-Host "- Internal Service: respondr-service.$Namespace.svc.cluster.local" -ForegroundColor Cyan
        Write-Host "- Ingress Host: $hostname" -ForegroundColor Cyan
        Write-Host "- API Endpoint: https://$hostname/api/responders" -ForegroundColor Cyan
        Write-Host "- Webhook Endpoint: https://$hostname/webhook" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "SSL Certificate:" -ForegroundColor Green
        if ($certificateReady) {
            Write-Host "- Let's Encrypt certificate: ✅ Ready" -ForegroundColor Green
        } else {
            Write-Host "- Let's Encrypt certificate: ⏳ Still processing" -ForegroundColor Yellow
        }
        Write-Host ""
        Write-Host "Authentication:" -ForegroundColor Green
        if ($UseOAuth2) {
            Write-Host "- OAuth2 Proxy with Azure AD authentication is configured" -ForegroundColor Cyan
            Write-Host "- Users will be challenged to sign in with Entra/Azure AD" -ForegroundColor Cyan
            Write-Host "- Authentication handled by oauth2-proxy sidecar container" -ForegroundColor Cyan
        } else {
            Write-Host "- Entra (Azure AD) authentication is configured via Application Gateway" -ForegroundColor Cyan
            Write-Host "- Workload Identity is configured for Azure resource access" -ForegroundColor Cyan
            Write-Host "- All traffic will be authenticated via Microsoft Entra" -ForegroundColor Cyan
        }
    } else {
        Write-Error "Deployment failed!"
        exit 1
    }
} else {
    Write-Host "DRY RUN: Would deploy the following configuration:" -ForegroundColor Cyan
    Get-Content $tempFile
}

# Clean up temp file (only for non-OAuth2 deployments)
if (-not $UseOAuth2) {
    Remove-Item $tempFile -ErrorAction SilentlyContinue
}

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
Write-Host "✅ Configured Let's Encrypt SSL certificates via cert-manager" -ForegroundColor Green
Write-Host "✅ Created namespace: $Namespace" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "1. Verify DNS configuration points to Application Gateway IP" -ForegroundColor White
Write-Host "2. Wait for Let's Encrypt certificate to be issued (if not ready yet)" -ForegroundColor White
Write-Host "3. Test authentication: Navigate to https://$hostname in browser" -ForegroundColor White
Write-Host "4. Test API endpoint: https://$hostname/api/responders (after authentication)" -ForegroundColor White
Write-Host "5. Send test webhook: Use authenticated endpoint for webhook testing" -ForegroundColor White
Write-Host ""
Write-Host "Certificate Status Commands:" -ForegroundColor Yellow
Write-Host "kubectl get certificate respondr-tls-letsencrypt -n $Namespace" -ForegroundColor White
Write-Host "kubectl describe certificate respondr-tls-letsencrypt -n $Namespace" -ForegroundColor White
Write-Host "kubectl get certificaterequests -n $Namespace" -ForegroundColor White
Write-Host ""
Write-Host "Security Features Enabled:" -ForegroundColor Green
if ($UseOAuth2) {
    Write-Host "✅ OAuth2 Proxy with Microsoft Entra (Azure AD) authentication" -ForegroundColor Green
    Write-Host "✅ Automatic Azure AD sign-in challenge for all users" -ForegroundColor Green
    Write-Host "✅ Sidecar authentication pattern with transparent integration" -ForegroundColor Green
} else {
    Write-Host "✅ Microsoft Entra (Azure AD) authentication via Application Gateway" -ForegroundColor Green
    Write-Host "✅ Azure Workload Identity for secure access to Azure resources" -ForegroundColor Green
}
Write-Host "✅ Let's Encrypt SSL/TLS certificates with automatic renewal" -ForegroundColor Green
Write-Host "✅ Dedicated namespace isolation" -ForegroundColor Green
