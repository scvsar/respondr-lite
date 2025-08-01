# Purge-deleted-resources.ps1
# This script purges soft-deleted resources to allow clean redeployment

param (
    [Parameter(Mandatory=$true)]
    [string]$ResourceGroupName,
    
    [Parameter(Mandatory=$false)]
    [string]$Location = "westus",
    
    [Parameter(Mandatory=$false)]
    [string]$SubscriptionId = (az account show --query id -o tsv)
)

Write-Host "Checking for soft-deleted resources in $ResourceGroupName..." -ForegroundColor Yellow

# Get soft-deleted Cognitive Services accounts
Write-Host "Checking for soft-deleted OpenAI accounts..." -ForegroundColor Yellow
try {
    # Directly check the Azure Cognitive Services API for soft-deleted accounts
    $deletedAccountId = "/subscriptions/$SubscriptionId/providers/Microsoft.CognitiveServices/locations/$Location/resourceGroups/$ResourceGroupName/deletedAccounts/response-openai-account"
    
    Write-Host "Attempting to purge soft-deleted OpenAI account..." -ForegroundColor Yellow
    az resource delete --ids $deletedAccountId --api-version 2023-05-01 --verbose
    Write-Host "Purged soft-deleted OpenAI account" -ForegroundColor Green
} catch {
    Write-Host "No soft-deleted OpenAI accounts found or error purging: $_" -ForegroundColor Yellow
}

# Check for existing storage accounts with the same name pattern
Write-Host "Checking for storage account name conflicts..." -ForegroundColor Yellow
$storagePrefix = "responsestorage"
$existingStorageAccounts = az storage account list --query "[?starts_with(name, '$storagePrefix')].name" -o tsv

if ($existingStorageAccounts) {
    Write-Host "Found storage accounts with prefix '$storagePrefix':" -ForegroundColor Yellow
    Write-Host $existingStorageAccounts -ForegroundColor Cyan
    Write-Host "If these are not in your resource group, consider using a different storage account name." -ForegroundColor Yellow
} else {
    Write-Host "No existing storage accounts found with prefix '$storagePrefix'." -ForegroundColor Green
}

Write-Host "Resource cleanup check complete." -ForegroundColor Green
