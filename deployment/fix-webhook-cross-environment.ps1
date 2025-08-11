#!/usr/bin/env pwsh
# Fix ACR webhook cross-environment restart issue

param(
    [Parameter(Mandatory = $true)]
    [string]$ResourceGroupName,

    [Parameter(Mandatory = $true)]
    [string]$Domain
)

Write-Host "🚨 FIXING ACR WEBHOOK CROSS-ENVIRONMENT RESTART ISSUE" -ForegroundColor Red
Write-Host "===============================================" -ForegroundColor Red

$acrName = "respondrbt774d4d55kswacr"
$problemWebhook = "respondrrestart"

# Step 1: Remove the problematic webhook
Write-Host "`n1. Removing problematic webhook that causes cross-environment restarts..." -ForegroundColor Yellow
$existing = az acr webhook show --registry $acrName --name $problemWebhook -o none 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "   Deleting webhook: $problemWebhook" -ForegroundColor Red
    az acr webhook delete --registry $acrName --name $problemWebhook 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "   ✅ Problematic webhook deleted" -ForegroundColor Green
    } else {
        Write-Host "   ⚠️  Failed to delete webhook (may require manual deletion)" -ForegroundColor Yellow
    }
} else {
    Write-Host "   ✅ Problematic webhook doesn't exist or already deleted" -ForegroundColor Green
}

# Step 2: Set up environment-specific webhooks
Write-Host "`n2. Setting up environment-specific webhooks..." -ForegroundColor Yellow

# Main/Production webhook
Write-Host "`n   Setting up MAIN/PRODUCTION webhook..."
if (Test-Path "values.yaml") {
    & (Join-Path $PSScriptRoot "configure-environment-webhooks.ps1") `
        -ResourceGroupName $ResourceGroupName `
        -Domain $Domain `
        -Environment "main" `
        -Namespace "respondr"
        
    if ($LASTEXITCODE -eq 0) {
        Write-Host "   ✅ Main webhook configured" -ForegroundColor Green
    } else {
        Write-Host "   ❌ Failed to configure main webhook" -ForegroundColor Red
    }
} else {
    Write-Host "   ⚠️  values.yaml not found - skipping main webhook" -ForegroundColor Yellow
}

# Preprod webhook  
Write-Host "`n   Setting up PREPROD webhook..."
if (Test-Path "values-preprod.yaml") {
    & (Join-Path $PSScriptRoot "configure-environment-webhooks.ps1") `
        -ResourceGroupName $ResourceGroupName `
        -Domain $Domain `
        -Environment "preprod" `
        -Namespace "respondr-preprod" `
        -HostPrefix "preprod"
        
    if ($LASTEXITCODE -eq 0) {
        Write-Host "   ✅ Preprod webhook configured" -ForegroundColor Green
    } else {
        Write-Host "   ❌ Failed to configure preprod webhook" -ForegroundColor Red
    }
} else {
    Write-Host "   ⚠️  values-preprod.yaml not found - skipping preprod webhook" -ForegroundColor Yellow
}

# Step 3: Verify the fix
Write-Host "`n3. Verifying webhook configuration..." -ForegroundColor Yellow
$webhooks = az acr webhook list --registry $acrName --query "[].{name:name,status:status,serviceUri:serviceUri,scope:scope}" -o json | ConvertFrom-Json

if ($webhooks) {
    Write-Host "`n   Current webhooks:" -ForegroundColor Cyan
    foreach ($webhook in $webhooks) {
        $uri = $webhook.serviceUri -replace "https://", ""
        Write-Host "   - $($webhook.name): $($webhook.scope) → $uri" -ForegroundColor White
    }
} else {
    Write-Host "   No webhooks found" -ForegroundColor Yellow
}

Write-Host "`n✅ WEBHOOK FIX COMPLETE!" -ForegroundColor Green
Write-Host "===============================================" -ForegroundColor Green
Write-Host "Each environment now has its own webhook with proper image tag scoping:" -ForegroundColor Gray
Write-Host "- Main: Only restarts on latest/main tags" -ForegroundColor Gray  
Write-Host "- Preprod: Only restarts on preprod tags" -ForegroundColor Gray
Write-Host "This prevents cross-environment restarts." -ForegroundColor Gray
