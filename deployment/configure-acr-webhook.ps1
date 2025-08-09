param(
    [Parameter(Mandatory = $true)]
    [string]$ResourceGroupName,

    [Parameter(Mandatory = $true)]
    [string]$Domain,

    [Parameter(Mandatory = $false)]
    [string]$WebhookName = "respondr-restart"
)

Write-Host "🪝 Configuring ACR webhook for automatic AKS rollouts..." -ForegroundColor Cyan

# Ensure we are in the script directory for relative paths
$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptPath

# Load values.yaml for ACR info and hostname
if (-not (Test-Path "values.yaml")) {
    Write-Error "values.yaml not found. Run generate-values.ps1 first."
    exit 1
}
$values = Get-Content "values.yaml" -Raw
$acrName = ($values | Select-String "acrName: \"([^"]+)\"").Matches[0].Groups[1].Value
$hostname = ($values | Select-String "hostname: \"([^"]+)\"").Matches[0].Groups[1].Value
if (-not $hostname) { $hostname = "respondr.$Domain" }

# Load secrets.yaml for ACR_WEBHOOK_TOKEN
if (-not (Test-Path "secrets.yaml")) {
    Write-Error "secrets.yaml not found. Run create-secrets.ps1 first."
    exit 1
}
$secretsRaw = Get-Content "secrets.yaml" -Raw
$acrTokenMatch = $secretsRaw | Select-String "ACR_WEBHOOK_TOKEN:\s*\"?([^\"\r\n]+)\"?"
if (-not $acrTokenMatch) {
    Write-Error "ACR_WEBHOOK_TOKEN not found in secrets.yaml"
    exit 1
}
$acrWebhookToken = $acrTokenMatch.Matches[0].Groups[1].Value.Trim()

$uri = "https://$hostname/internal/acr-webhook"
$headersArg = "X-ACR-Token=$acrWebhookToken"

Write-Host "Registry: $acrName" -ForegroundColor White
Write-Host "Webhook:  $WebhookName" -ForegroundColor White
Write-Host "URI:      $uri" -ForegroundColor White

# Check if webhook exists
$existing = az acr webhook show --registry $acrName --name $WebhookName -o none 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "Webhook exists. Updating..." -ForegroundColor Yellow
    az acr webhook update --registry $acrName --name $WebhookName --actions push --uri $uri --headers $headersArg | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Update failed; recreating webhook to ensure correct configuration."
        az acr webhook delete --registry $acrName --name $WebhookName | Out-Null
        az acr webhook create --registry $acrName --name $WebhookName --actions push --uri $uri --headers $headersArg --scope "respondr:*" | Out-Null
        if ($LASTEXITCODE -ne 0) { Write-Error "Failed to recreate ACR webhook"; exit 1 }
    }
} else {
    Write-Host "Creating webhook..." -ForegroundColor Yellow
    az acr webhook create --registry $acrName --name $WebhookName --actions push --uri $uri --headers $headersArg --scope "respondr:*" | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Error "Failed to create ACR webhook"; exit 1 }
}

Write-Host "✅ ACR webhook configured: pushes will POST to $uri and trigger AKS rollout" -ForegroundColor Green
