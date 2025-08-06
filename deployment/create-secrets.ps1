<#
.SYNOPSIS
    Creates the Kubernetes secrets file for the Respondr application
    
.DESCRIPTION
    This script automates the creation of the secrets.yaml file by:
    1. Retrieving Azure OpenAI credentials from your Azure deployment
    2. Creating a secrets.yaml file based on the template
    3. Filling in the correct values
    
.PARAMETER ResourceGroupName
    Name of the Azure resource group where resources are deployed
    
.PARAMETER OpenAIDeploymentName
    Name of the Azure OpenAI deployment model (optional - will auto-detect if not specified)
    
.PARAMETER ApiVersion
    API version to use for Azure OpenAI (default: 2025-01-01-preview)
    
.EXAMPLE
    .\create-secrets.ps1 -ResourceGroupName respondr
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$ResourceGroupName,
    
    [Parameter(Mandatory=$false)]
    [string]$OpenAIDeploymentName,
    
    [Parameter(Mandatory=$false)]
    [string]$ApiVersion = "2024-12-01-preview"
)

Write-Host "Respondr - Creating Kubernetes Secrets File" -ForegroundColor Green
Write-Host "=====================================" -ForegroundColor Green

# Ensure we're in the correct directory
$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptPath

# Check that template exists
$templatePath = Join-Path $scriptPath "secrets-template.yaml"
$secretsPath = Join-Path $scriptPath "secrets.yaml"

if (-not (Test-Path $templatePath)) {
    Write-Error "Template file not found at $templatePath"
    exit 1
}

# Step 1: Get Azure OpenAI credentials
Write-Host "`nRetrieving Azure OpenAI credentials..." -ForegroundColor Yellow

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
    
    Write-Host "  Retrieved Azure OpenAI endpoint and key successfully" -ForegroundColor Green
    
    # Step 1.5: Check for actual model deployments
    Write-Host "  Checking for available model deployments..." -ForegroundColor Yellow
    
    $actualDeploymentName = $OpenAIDeploymentName
    $deploymentValidated = $false
    
    try {
        # Get list of deployed models
        $deploymentsCommand = "az cognitiveservices account deployment list -n `"$openAIName`" -g `"$ResourceGroupName`" --query `"[].name`" -o json"
        $deploymentsJson = Invoke-Expression $deploymentsCommand
        $deployments = $deploymentsJson | ConvertFrom-Json
        
        # Ensure $deployments is always treated as an array
        if ($deployments -is [string]) {
            $deployments = @($deployments)
        } elseif ($deployments -and -not ($deployments -is [array])) {
            $deployments = @($deployments)
        }
        
        if ($deployments -and @($deployments).Count -gt 0) {
            Write-Host "  Found deployments: $($deployments -join ', ')" -ForegroundColor Cyan
            Write-Host "  Deployment count: $(@($deployments).Count)" -ForegroundColor Gray
            
            if ($OpenAIDeploymentName) {
                # Check if the specified deployment exists
                if ($deployments -contains $OpenAIDeploymentName) {
                    Write-Host "  Specified deployment '$OpenAIDeploymentName' found" -ForegroundColor Green
                    $deploymentValidated = $true
                } else {
                    Write-Host "  ⚠️  Specified deployment '$OpenAIDeploymentName' not found in deployed models" -ForegroundColor Yellow
                    $actualDeploymentName = "YOUR_DEPLOYMENT_NAME_HERE"
                }
            } else {
                # No deployment specified, try to find a reasonable default
                $preferredModels = @("gpt-4o-mini", "gpt-4o", "gpt-4", "gpt-35-turbo")
                $foundModel = $null
                
                foreach ($preferred in $preferredModels) {
                    if ($deployments -contains $preferred) {
                        $foundModel = $preferred
                        break
                    }
                }
                
                if ($foundModel) {
                    $actualDeploymentName = $foundModel
                    $deploymentValidated = $true
                    Write-Host "  Using found deployment: '$foundModel'" -ForegroundColor Green
                } else {
                    # Use the first available deployment
                    $actualDeploymentName = $deployments[0]
                    $deploymentValidated = $true
                    Write-Host "  Using first available deployment: '$actualDeploymentName'" -ForegroundColor Green
                }
            }
        } else {
            Write-Host "  ⚠️  No model deployments found in OpenAI account" -ForegroundColor Yellow
            $actualDeploymentName = "YOUR_DEPLOYMENT_NAME_HERE"
        }
    } catch {
        Write-Host "  ⚠️  Could not retrieve model deployments: $_" -ForegroundColor Yellow
        $actualDeploymentName = "YOUR_DEPLOYMENT_NAME_HERE"
    }
}
catch {
    Write-Error "Error retrieving Azure OpenAI credentials: $_"
    exit 1
}

# Step 2: Create secrets.yaml from template
Write-Host "`nCreating secrets.yaml file..." -ForegroundColor Yellow

try {
    # Copy the template
    Copy-Item -Path $templatePath -Destination $secretsPath -Force
    
    # Read the template content
    $secretsContent = Get-Content -Path $secretsPath -Raw
    
    # Generate a secure webhook API key (64-character hex string)
    $webhookApiKey = -join ((1..64) | ForEach-Object { '{0:x}' -f (Get-Random -Maximum 16) })
    
    # Replace placeholders with actual values
    $secretsContent = $secretsContent -replace 'YOUR_AZURE_OPENAI_API_KEY_HERE', $openAIKey
    $secretsContent = $secretsContent -replace 'YOUR_AZURE_OPENAI_ENDPOINT_HERE', $openAIEndpoint
    $secretsContent = $secretsContent -replace 'YOUR_DEPLOYMENT_NAME_HERE', $actualDeploymentName
    $secretsContent = $secretsContent -replace 'YOUR_API_VERSION_HERE', $ApiVersion
    $secretsContent = $secretsContent -replace 'YOUR_WEBHOOK_API_KEY_HERE', $webhookApiKey
    
    # Write the updated content
    Set-Content -Path $secretsPath -Value $secretsContent
    
    Write-Host "  Created secrets file at: $secretsPath" -ForegroundColor Green
}
catch {
    Write-Error "Error creating secrets.yaml file: $_"
    exit 1
}

# Step 3: Verify (without displaying sensitive info)
Write-Host "`nVerifying secrets file..." -ForegroundColor Yellow

$keyStatus = if ($openAIKey) { "Valid key found" } else { "MISSING" }
$deploymentStatus = if ($deploymentValidated) { "Validated" } else { "⚠️  Placeholder (manual setup required)" }
$webhookKeyStatus = if ($webhookApiKey) { "Generated (64-char hex)" } else { "MISSING" }

Write-Host "  Azure OpenAI Endpoint: $openAIEndpoint" -ForegroundColor Cyan
Write-Host "  Azure OpenAI API Key: $keyStatus" -ForegroundColor Cyan
Write-Host "  Azure OpenAI Deployment: $actualDeploymentName ($deploymentStatus)" -ForegroundColor Cyan
Write-Host "  Azure OpenAI API Version: $ApiVersion" -ForegroundColor Cyan
Write-Host "  Webhook API Key: $webhookKeyStatus" -ForegroundColor Cyan

# Validate the secrets.yaml file was created with the correct format
if (Test-Path $secretsPath) {
    $yamlContent = Get-Content -Path $secretsPath -Raw
    if ($yamlContent -match "AZURE_OPENAI_API_KEY" -and 
        $yamlContent -match $openAIEndpoint -and
        $yamlContent -match $actualDeploymentName) {
        Write-Host "  Secrets file validation passed" -ForegroundColor Green
    }
    else {
        Write-Host "  Warning: Secrets file may not contain all expected values" -ForegroundColor Yellow
    }
}

# Provide additional guidance if deployment wasn't validated
if (-not $deploymentValidated) {
    Write-Host "`n⚠️  IMPORTANT: Manual setup required!" -ForegroundColor Yellow
    Write-Host "The deployment name 'YOUR_DEPLOYMENT_NAME_HERE' is a placeholder." -ForegroundColor Yellow
    Write-Host "Please:" -ForegroundColor Yellow
    Write-Host "1. Deploy a model in your Azure OpenAI account" -ForegroundColor White
    Write-Host "2. Edit secrets.yaml and replace 'YOUR_DEPLOYMENT_NAME_HERE' with your actual deployment name" -ForegroundColor White
    Write-Host "3. Or re-run this script with -OpenAIDeploymentName parameter" -ForegroundColor White
}

Write-Host "`nSecrets file created successfully!" -ForegroundColor Green
Write-Host "You can now deploy your application using:" -ForegroundColor Yellow
Write-Host ""
Write-Host "📋 Deployment Options:" -ForegroundColor Blue
Write-Host "  1. Unified deployment (recommended):" -ForegroundColor Yellow
Write-Host "     .\deploy-unified.ps1                    # OAuth2 protected (secure)" -ForegroundColor Green
Write-Host "     .\deploy-unified.ps1 -NoOAuth2          # Direct access (simple)" -ForegroundColor Cyan
Write-Host ""
Write-Host "  2. Manual deployment:" -ForegroundColor Yellow
Write-Host "     kubectl apply -f secrets.yaml" -ForegroundColor White
Write-Host "     kubectl apply -f respondr-k8s.yaml      # OAuth2 version" -ForegroundColor White
Write-Host "     kubectl apply -f respondr-k8s-oauth2.yaml  # OAuth2 version (legacy)" -ForegroundColor White
Write-Host ""
Write-Host "  3. Legacy deployment scripts:" -ForegroundColor Yellow
Write-Host "     .\deploy-to-k8s.ps1" -ForegroundColor White
