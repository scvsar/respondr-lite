#!/usr/bin/env pwsh
# Validation script for preprod deployment automation

param(
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

Write-Host "🧪 VALIDATING PREPROD DEPLOYMENT AUTOMATION" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan

$issues = @()

# Test 1: Check if deploy-complete.ps1 handles ImageTag properly
Write-Host "`n🔍 Test 1: Checking ImageTag handling in deploy-complete.ps1..." -ForegroundColor Yellow
$deployScript = Get-Content "deploy-complete.ps1" -Raw
if ($deployScript -match 'imageTag.*=.*\$ImageTag' -or $deployScript -match 'imageTag.*=.*valuesContent.*imageTag') {
    Write-Host "✅ deploy-complete.ps1 uses dynamic ImageTag" -ForegroundColor Green
} else {
    $issues += "❌ deploy-complete.ps1 may still use hardcoded image tags"
}

# Test 2: Check secret copying logic
Write-Host "`n🔍 Test 2: Checking secret copying logic..." -ForegroundColor Yellow
if ($deployScript -match 'copy.*secret.*main.*namespace' -or $deployScript -match 'kubectl get secret.*respondr.*-o yaml') {
    Write-Host "✅ deploy-complete.ps1 includes secret copying logic" -ForegroundColor Green
} else {
    $issues += "❌ deploy-complete.ps1 missing secret copying for preprod"
}

# Test 3: Check ACR-AKS integration
Write-Host "`n🔍 Test 3: Checking ACR-AKS integration..." -ForegroundColor Yellow
if ($deployScript -match 'attach-acr' -or $deployScript -match 'aks update.*acr') {
    Write-Host "✅ deploy-complete.ps1 includes ACR-AKS integration" -ForegroundColor Green
} else {
    $issues += "❌ deploy-complete.ps1 missing ACR-AKS integration"
}

# Test 4: Check README completeness
Write-Host "`n🔍 Test 4: Checking README completeness..." -ForegroundColor Yellow
if (Test-Path "README-preprod.md") {
    $readme = Get-Content "README-preprod.md" -Raw
    $hasMethod1 = $readme -match 'Method 1.*Automated'
    $hasMethod2 = $readme -match 'Method 2.*Step-by-Step'
    $hasTroubleshooting = $readme -match 'Troubleshooting'
    
    if ($hasMethod1 -and $hasMethod2 -and $hasTroubleshooting) {
        Write-Host "✅ README-preprod.md is comprehensive" -ForegroundColor Green
    } else {
        $issues += "❌ README-preprod.md missing sections (Methods: $hasMethod1/$hasMethod2, Troubleshooting: $hasTroubleshooting)"
    }
} else {
    $issues += "❌ README-preprod.md not found"
}

# Test 5: Check template supports replicas configuration
Write-Host "`n🔍 Test 5: Checking template supports replicas..." -ForegroundColor Yellow
if (Test-Path "respondr-k8s-unified-template.yaml") {
    $template = Get-Content "respondr-k8s-unified-template.yaml" -Raw
    if ($template -match 'replicas:.*REPLICAS_PLACEHOLDER') {
        Write-Host "✅ Template supports configurable replicas" -ForegroundColor Green
    } else {
        $issues += "❌ Template may have hardcoded replicas"
    }
} else {
    $issues += "❌ respondr-k8s-unified-template.yaml not found"
}

# Test 6: Check process-template.ps1 handles replicas
Write-Host "`n🔍 Test 6: Checking process-template.ps1 handles replicas..." -ForegroundColor Yellow
if (Test-Path "process-template.ps1") {
    $processScript = Get-Content "process-template.ps1" -Raw
    if ($processScript -match 'REPLICAS_PLACEHOLDER') {
        Write-Host "✅ process-template.ps1 handles replicas placeholder" -ForegroundColor Green
    } else {
        $issues += "❌ process-template.ps1 missing replicas placeholder handling"
    }
} else {
    $issues += "❌ process-template.ps1 not found"
}

# Summary
Write-Host "`n📊 VALIDATION SUMMARY" -ForegroundColor Cyan
Write-Host "=====================" -ForegroundColor Cyan

if ($issues.Count -eq 0) {
    Write-Host "🎉 ALL TESTS PASSED!" -ForegroundColor Green
    Write-Host "Preprod deployment automation should work end-to-end without manual intervention." -ForegroundColor Green
    Write-Host ""
    Write-Host "✅ Key Features Validated:" -ForegroundColor Green
    Write-Host "  - Dynamic image tag building (no hardcoded latest)" -ForegroundColor White
    Write-Host "  - Automatic secret copying from main namespace" -ForegroundColor White
    Write-Host "  - ACR-AKS integration verification" -ForegroundColor White
    Write-Host "  - Comprehensive documentation" -ForegroundColor White
    Write-Host "  - Configurable replica counts" -ForegroundColor White
    
    if (-not $DryRun) {
        Write-Host ""
        Write-Host "🚀 Ready to deploy preprod with:" -ForegroundColor Yellow
        Write-Host ".\deploy-complete.ps1 -ResourceGroupName respondr -Domain rtreit.com -Namespace respondr-preprod -HostPrefix preprod -ImageTag preprod -SkipInfrastructure" -ForegroundColor White
    }
} else {
    Write-Host "❌ VALIDATION FAILED" -ForegroundColor Red
    Write-Host "Issues found:" -ForegroundColor Red
    $issues | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
    exit 1
}
