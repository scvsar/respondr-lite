param(
    [string]$ResourceGroup = "respondr-ppe-eastus2"
)

$ErrorActionPreference = "Stop"

Write-Host "Fetching secrets for Resource Group: $ResourceGroup" -ForegroundColor Cyan

# 1. Find Resources
Write-Host "Locating resources..."
$StorageAccount = az storage account list -g $ResourceGroup --query "[0].name" -o tsv
if (-not $StorageAccount) { Write-Error "No Storage Account found in $ResourceGroup"; exit 1 }

$OpenAI = az cognitiveservices account list -g $ResourceGroup --query "[0].name" -o tsv
if (-not $OpenAI) { Write-Error "No OpenAI Account found in $ResourceGroup"; exit 1 }

$ContainerApp = az containerapp list -g $ResourceGroup --query "[0].name" -o tsv
if (-not $ContainerApp) { Write-Error "No Container App found in $ResourceGroup"; exit 1 }

Write-Host "Found:"
Write-Host "  Storage: $StorageAccount"
Write-Host "  OpenAI:  $OpenAI"
Write-Host "  App:     $ContainerApp"
Write-Host ""

# 2. Fetch Secrets
Write-Host "Fetching keys..."
$ConnStr    = az storage account show-connection-string -n $StorageAccount -g $ResourceGroup --query connectionString -o tsv
$AiKey      = az cognitiveservices account keys list -n $OpenAI -g $ResourceGroup --query key1 -o tsv
$AiEndpoint = az cognitiveservices account show -n $OpenAI -g $ResourceGroup --query properties.endpoint -o tsv

# 3. Output
Write-Host "----------------------------------------------------------------" -ForegroundColor Green
Write-Host "SECRETS (Copy these to your .env or Container App settings)" -ForegroundColor Green
Write-Host "----------------------------------------------------------------" -ForegroundColor Green
Write-Host ""
Write-Host "AZURE_STORAGE_CONNECTION_STRING=$ConnStr"
Write-Host ""
Write-Host "AZURE_OPENAI_API_KEY=$AiKey"
Write-Host ""
Write-Host "AZURE_OPENAI_ENDPOINT=$AiEndpoint"
Write-Host ""
Write-Host "----------------------------------------------------------------" -ForegroundColor Green

# 4. Optional Update Prompt
$response = Read-Host "Do you want to automatically update the Container App ($ContainerApp) with these values? (y/n)"
if ($response -eq 'y') {
    Write-Host "Updating Container App... this may take a minute..." -ForegroundColor Cyan
    az containerapp update -n $ContainerApp -g $ResourceGroup --set-env-vars `
        AZURE_STORAGE_CONNECTION_STRING=$ConnStr `
        AZURE_OPENAI_API_KEY=$AiKey `
        AZURE_OPENAI_ENDPOINT=$AiEndpoint
    Write-Host "Update complete!" -ForegroundColor Green
}
