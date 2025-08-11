#!/usr/bin/env pwsh
# Configure environment-specific ACR webhooks to prevent cross-environment restarts

param(
    [Parameter(Mandatory = $true)]
    [string]$ResourceGroupName,

    [Parameter(Mandatory = $true)]
    [string]$Domain,

    [Parameter(Mandatory = $false)]
    [string]$Environment = "main",  # main or preprod

    [Parameter(Mandatory = $false)]
    [string]$Namespace = "respondr",

    [Parameter(Mandatory = $false)]
    [string]$HostPrefix = ""
)

Write-Host "🪝 Configuring environment-specific ACR webhook..." -ForegroundColor Cyan
Write-Host "Environment: $Environment" -ForegroundColor White
Write-Host "Namespace: $Namespace" -ForegroundColor White

# Ensure we are in the script directory for relative paths
$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptPath

# Determine the correct values file based on environment
$valuesFile = if ($Environment -eq "preprod") { "values-preprod.yaml" } else { "values.yaml" }
if (-not (Test-Path $valuesFile)) {
    Write-Error "$valuesFile not found. Run generate-values.ps1 first for the $Environment environment."
    exit 1
}

# Load values for ACR info and hostname
$values = Get-Content $valuesFile -Raw
$acrName = ($values | Select-String 'acrName: "([^"]+)"').Matches[0].Groups[1].Value
$hostname = ($values | Select-String 'hostname: "([^"]+)"').Matches[0].Groups[1].Value

if (-not $hostname) { 
    $hostname = if ($HostPrefix) { "$HostPrefix.$Domain" } else { "respondr.$Domain" }
}

# Determine the correct secrets file
$secretsFile = if ($Environment -eq "preprod") { "secrets-preprod.yaml" } else { "secrets.yaml" }
if (-not (Test-Path $secretsFile)) {
    Write-Error "$secretsFile not found. Run create-secrets.ps1 first for the $Environment environment."
    exit 1
}

# Load secrets for ACR_WEBHOOK_TOKEN
$secretsRaw = Get-Content $secretsFile -Raw
$acrTokenMatch = $secretsRaw | Select-String 'ACR_WEBHOOK_TOKEN:\s*"?([^"\r\n]+)"?'
if (-not $acrTokenMatch) {
    Write-Error "ACR_WEBHOOK_TOKEN not found in $secretsFile"
    exit 1
}
$acrWebhookToken = $acrTokenMatch.Matches[0].Groups[1].Value.Trim()

# Configure environment-specific webhook
$webhookName = "respondr-$Environment"
$uri = "https://$hostname/internal/acr-webhook"
$headersArg = "X-ACR-Token=$acrWebhookToken"

# Define scope based on environment - this is the KEY FIX
$scope = if ($Environment -eq "preprod") { 
    "respondr:preprod*"  # Only trigger on preprod tags
} else { 
    "respondr:latest,respondr:main*"  # Only trigger on latest/main tags, NOT preprod
}

Write-Host "Registry: $acrName" -ForegroundColor White
Write-Host "Webhook:  $webhookName" -ForegroundColor White
Write-Host "URI:      $uri" -ForegroundColor White
Write-Host "Scope:    $scope" -ForegroundColor Yellow

# Check if webhook exists
$existing = az acr webhook show --registry $acrName --name $webhookName -o none 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "Webhook exists. Updating..." -ForegroundColor Yellow
    az acr webhook update --registry $acrName --name $webhookName --actions push --uri $uri --headers $headersArg --scope $scope | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Update failed; recreating webhook."
        az acr webhook delete --registry $acrName --name $webhookName | Out-Null
        az acr webhook create --registry $acrName --name $webhookName --actions push --uri $uri --headers $headersArg --scope $scope | Out-Null
        if ($LASTEXITCODE -ne 0) { Write-Error "Failed to recreate ACR webhook"; exit 1 }
    }
} else {
    Write-Host "Creating webhook..." -ForegroundColor Yellow
    az acr webhook create --registry $acrName --name $webhookName --actions push --uri $uri --headers $headersArg --scope $scope | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Error "Failed to create ACR webhook"; exit 1 }
}

Write-Host "✅ Environment-specific ACR webhook configured" -ForegroundColor Green
Write-Host "   Pushes matching '$scope' will POST to $uri" -ForegroundColor Gray
Write-Host "   This will trigger restarts in the '$Namespace' namespace only" -ForegroundColor Gray
