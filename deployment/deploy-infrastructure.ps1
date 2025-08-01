# Deploy-Infrastructure.ps1
# This script deploys the complete infrastructure for the response-tracking-render application

param (
    [Parameter(Mandatory=$false)]
    [string]$ResourceGroupName = "respondr",
    
    [Parameter(Mandatory=$false)]
    [string]$Location = "westus",
    
    [Parameter(Mandatory=$false)]
    [switch]$CleanupFirst,
    
    [Parameter(Mandatory=$false)]
    [switch]$SkipPurge
)

# Set error action preference
$ErrorActionPreference = "Stop"

# Login to Azure if not already logged in
try {
    $account = az account show --output none
} catch {
    Write-Host "Logging in to Azure..." -ForegroundColor Yellow
    az login
}

# Ensure resource group exists
$rgExists = az group exists --name $ResourceGroupName
if ($rgExists -eq "false") {
    Write-Host "Creating resource group $ResourceGroupName..." -ForegroundColor Yellow
    az group create --name $ResourceGroupName --location $Location
    Write-Host "Resource group created." -ForegroundColor Green
} else {
    Write-Host "Resource group $ResourceGroupName already exists." -ForegroundColor Green
}

# Run cleanup if requested
if ($CleanupFirst) {
    Write-Host "Running cleanup script..." -ForegroundColor Yellow
    & "$PSScriptRoot\cleanup.ps1" -ResourceGroupName $ResourceGroupName -Force
    
    # Wait for cleanup to complete
    Write-Host "Waiting for cleanup to complete (30 seconds)..." -ForegroundColor Yellow
    Start-Sleep -Seconds 30
    
    # Re-create resource group if it was deleted
    $rgExists = az group exists --name $ResourceGroupName
    if ($rgExists -eq "false") {
        Write-Host "Re-creating resource group $ResourceGroupName..." -ForegroundColor Yellow
        az group create --name $ResourceGroupName --location $Location
    }
}

# Purge deleted resources if needed and not skipped
if (-not $SkipPurge) {
    Write-Host "Running purge script for soft-deleted resources..." -ForegroundColor Yellow
    & "$PSScriptRoot\purge-deleted-resources.ps1" -ResourceGroupName $ResourceGroupName -Location $Location
}

# Deploy the Bicep template
Write-Host "Deploying Bicep template..." -ForegroundColor Yellow
$deployResult = az deployment group create --resource-group $ResourceGroupName --template-file "$PSScriptRoot\main.bicep" --location $Location
if ($LASTEXITCODE -ne 0) {
    Write-Host "Deployment failed. See error above." -ForegroundColor Red
    exit 1
}
Write-Host "Bicep deployment completed successfully." -ForegroundColor Green

# Run post-deployment script
Write-Host "Running post-deployment configuration..." -ForegroundColor Yellow
& "$PSScriptRoot\post-deploy.ps1" -ResourceGroupName $ResourceGroupName -Location $Location

Write-Host "Deployment completed successfully!" -ForegroundColor Green
Write-Host "You can now use the resources in resource group $ResourceGroupName." -ForegroundColor Green
