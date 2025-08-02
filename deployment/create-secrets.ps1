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
    Name of the Azure OpenAI deployment model (default: gpt-4o-mini)
    
.PARAMETER ApiVersion
    API version to use for Azure OpenAI (default: 2025-01-01-preview)
    
.EXAMPLE
    .\create-secrets.ps1 -ResourceGroupName respondr
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$ResourceGroupName,
    
    [Parameter(Mandatory=$false)]
    [string]$OpenAIDeploymentName = "gpt-4o-mini",
    
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
    
    # Replace placeholders with actual values
    $secretsContent = $secretsContent -replace 'YOUR_AZURE_OPENAI_API_KEY_HERE', $openAIKey
    $secretsContent = $secretsContent -replace 'https://westus.api.cognitive.microsoft.com/', $openAIEndpoint
    $secretsContent = $secretsContent -replace 'gpt-4o-mini', $OpenAIDeploymentName
    $secretsContent = $secretsContent -replace '2024-12-01-preview', $ApiVersion
    
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
Write-Host "  Azure OpenAI Endpoint: $openAIEndpoint" -ForegroundColor Cyan
Write-Host "  Azure OpenAI API Key: $keyStatus" -ForegroundColor Cyan
Write-Host "  Azure OpenAI Deployment: $OpenAIDeploymentName" -ForegroundColor Cyan
Write-Host "  Azure OpenAI API Version: $ApiVersion" -ForegroundColor Cyan

# Validate the secrets.yaml file was created with the correct format
if (Test-Path $secretsPath) {
    $yamlContent = Get-Content -Path $secretsPath -Raw
    if ($yamlContent -match "AZURE_OPENAI_API_KEY" -and 
        $yamlContent -match $openAIEndpoint -and
        $yamlContent -match $OpenAIDeploymentName) {
        Write-Host "  Secrets file validation passed" -ForegroundColor Green
    }
    else {
        Write-Host "  Warning: Secrets file may not contain all expected values" -ForegroundColor Yellow
    }
}

Write-Host "`nSecrets file created successfully!" -ForegroundColor Green
Write-Host "You can now deploy your application using:" -ForegroundColor Yellow
Write-Host "  kubectl apply -f secrets.yaml" -ForegroundColor Cyan
Write-Host "  kubectl apply -f respondr-k8s-deployment.yaml" -ForegroundColor Cyan
Write-Host "or use the deployment script:" -ForegroundColor Yellow
Write-Host "  .\deploy-to-k8s.ps1" -ForegroundColor Cyan
