#!/usr/bin/env pwsh
# Simple webhook creation script - run this manually to fix the webhook issue

Write-Host "🔧 CREATING ENVIRONMENT-SPECIFIC WEBHOOKS" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

$acrName = "respondrbt774d4d55kswacr"
$webhookToken = "4848506ea2b424311129b9eea1b8fecb0d0b4c00edcece67d23374b39f31bcdf"

Write-Host "`nStep 1: Creating MAIN environment webhook..." -ForegroundColor Yellow
Write-Host "Name: respondrmain"
Write-Host "URI: https://respondr.rtreit.com/internal/acr-webhook"
Write-Host "Scope: respondr:latest"

try {
    $result1 = az acr webhook create `
        --registry $acrName `
        --name "respondrmain" `
        --actions push `
        --uri "https://respondr.rtreit.com/internal/acr-webhook" `
        --headers "X-ACR-Token=$webhookToken" `
        --scope "respondr:latest" 2>&1
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✅ Main webhook created successfully" -ForegroundColor Green
    } else {
        Write-Host "❌ Main webhook failed: $result1" -ForegroundColor Red
    }
} catch {
    Write-Host "❌ Main webhook error: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host "`nStep 2: Creating PREPROD environment webhook..." -ForegroundColor Yellow
Write-Host "Name: respondrpreprod"
Write-Host "URI: https://preprod.rtreit.com/internal/acr-webhook"
Write-Host "Scope: respondr:preprod"

try {
    $result2 = az acr webhook create `
        --registry $acrName `
        --name "respondrpreprod" `
        --actions push `
        --uri "https://preprod.rtreit.com/internal/acr-webhook" `
        --headers "X-ACR-Token=$webhookToken" `
        --scope "respondr:preprod" 2>&1
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✅ Preprod webhook created successfully" -ForegroundColor Green
    } else {
        Write-Host "❌ Preprod webhook failed: $result2" -ForegroundColor Red
    }
} catch {
    Write-Host "❌ Preprod webhook error: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host "`nStep 3: Verifying webhook configuration..." -ForegroundColor Yellow
$webhooks = az acr webhook list --registry $acrName --query "[].{name:name,status:status,scope:scope,uri:serviceUri}" -o table 2>&1

if ($LASTEXITCODE -eq 0) {
    Write-Host "Current webhooks:"
    Write-Host $webhooks
} else {
    Write-Host "❌ Failed to list webhooks: $webhooks" -ForegroundColor Red
}

Write-Host "`n✅ WEBHOOK SETUP COMPLETE!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host "Main webhook: Responds to 'respondr:latest' pushes → Production" -ForegroundColor Gray
Write-Host "Preprod webhook: Responds to 'respondr:preprod' pushes → Preprod" -ForegroundColor Gray
Write-Host "This prevents cross-environment restarts!" -ForegroundColor Gray
