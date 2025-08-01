# Cleanup script for the response-tracking-render application
# This script removes all Azure resources created for the application

param (
    [Parameter(Mandatory=$true)]
    [string]$ResourceGroupName,

    [Parameter(Mandatory=$false)]
    [switch]$Force
)

if (-not $Force) {
    Write-Host "WARNING: This script will delete the following resource groups:" -ForegroundColor Red
    Write-Host "  - $ResourceGroupName" -ForegroundColor Yellow
    Write-Host "  - MC_${ResourceGroupName}_response-aks-cluster_*" -ForegroundColor Yellow
    
    $confirmation = Read-Host "Are you sure you want to proceed? (y/n)"
    if ($confirmation -ne 'y') {
        Write-Host "Operation cancelled." -ForegroundColor Green
        exit
    }
}

# Find the AKS-created resource group
$aksResourceGroup = az group list --query "[?starts_with(name, 'MC_${ResourceGroupName}_response-aks-cluster')].name" -o tsv

# Delete the AKS-created resource group first (if it exists)
if ($aksResourceGroup) {
    Write-Host "Deleting AKS-created resource group: $aksResourceGroup..." -ForegroundColor Yellow
    az group delete --name $aksResourceGroup --yes --no-wait
    Write-Host "Deletion of $aksResourceGroup initiated. This may take several minutes." -ForegroundColor Cyan
}

# Delete the main resource group
Write-Host "Deleting main resource group: $ResourceGroupName..." -ForegroundColor Yellow
az group delete --name $ResourceGroupName --yes --no-wait
Write-Host "Deletion of $ResourceGroupName initiated. This may take several minutes." -ForegroundColor Cyan

Write-Host "Resource deletion has been initiated. Check the Azure portal for deletion status." -ForegroundColor Green
