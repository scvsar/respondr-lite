# Sync .env file with current Kubernetes secrets
# This script reads the current secrets from Kubernetes and updates the .env file

param(
    [Parameter(Mandatory=$false)]
    [string]$Namespace = "respondr",
    [Parameter(Mandatory=$false)]
    [string]$SecretName = "respondr-secrets"
)

Write-Host "🔄 Syncing .env file with Kubernetes secrets..." -ForegroundColor Yellow

# Get current webhook API key from Kubernetes
$webhookApiKey = kubectl get secret $SecretName -n $Namespace -o jsonpath='{.data.WEBHOOK_API_KEY}' | ForEach-Object { [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($_)) }

if (-not $webhookApiKey) {
    Write-Error "Failed to retrieve webhook API key from Kubernetes secrets"
    exit 1
}

Write-Host "✅ Retrieved webhook API key from Kubernetes" -ForegroundColor Green

# Get Azure OpenAI settings from secrets
$azureOpenAIKey = kubectl get secret $SecretName -n $Namespace -o jsonpath='{.data.AZURE_OPENAI_API_KEY}' | ForEach-Object { [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($_)) }
$azureOpenAIEndpoint = kubectl get secret $SecretName -n $Namespace -o jsonpath='{.data.AZURE_OPENAI_ENDPOINT}' | ForEach-Object { [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($_)) }
$azureOpenAIDeployment = kubectl get secret $SecretName -n $Namespace -o jsonpath='{.data.AZURE_OPENAI_DEPLOYMENT}' | ForEach-Object { [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($_)) }
$azureOpenAIVersion = kubectl get secret $SecretName -n $Namespace -o jsonpath='{.data.AZURE_OPENAI_API_VERSION}' | ForEach-Object { [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($_)) }

# Create .env file in backend directory
$backendPath = Join-Path (Split-Path $PSScriptRoot -Parent) "backend"
$envPath = Join-Path $backendPath ".env"

$envContent = @"
# Azure OpenAI Configuration
AZURE_OPENAI_API_KEY=$azureOpenAIKey
AZURE_OPENAI_ENDPOINT=$azureOpenAIEndpoint
AZURE_OPENAI_DEPLOYMENT=$azureOpenAIDeployment
AZURE_OPENAI_API_VERSION=$azureOpenAIVersion

# Webhook Security
WEBHOOK_API_KEY=$webhookApiKey

# Local Development
DEBUG=true
"@

Set-Content -Path $envPath -Value $envContent
Write-Host "✅ Updated .env file at: $envPath" -ForegroundColor Green
Write-Host "🔑 Webhook API Key: $webhookApiKey" -ForegroundColor Cyan
