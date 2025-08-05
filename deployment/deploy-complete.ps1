#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Complete end-to-end deployment script for Respondr application with HTTPS and Entra authentication.

.DESCRIPTION
    This script performs the complete deployment workflow:
    1. Infrastructure deployment (Bicep)
    2. Post-deployment configuration (AGIC, identities, auth setup)
    3. HTTPS certificate configuration
    4. Application deployment to Kubernetes
    5. DNS verification and testing

.PARAMETER ResourceGroupName
    The Azure resource group name to deploy to.

.PARAMETER Location
    The Azure region to deploy to (default: westus).

.PARAMETER Domain
    The domain to use for the application (default: paincave.pro).

.PARAMETER SkipInfrastructure
    Skip the infrastructure deployment step.

.PARAMETER SkipImageBuild
    Skip the Docker image build step.

.EXAMPLE
    .\deploy-complete.ps1 -ResourceGroupName "respondr" -Domain "paincave.pro"
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$ResourceGroupName,
    
    [Parameter(Mandatory=$false)]
    [string]$Location = "westus",
    
    [Parameter(Mandatory=$false)]
    [string]$Domain = "paincave.pro",
    
    [Parameter(Mandatory=$false)]
    [switch]$SkipInfrastructure,
    
    [Parameter(Mandatory=$false)]
    [switch]$SkipImageBuild,
    
    [Parameter(Mandatory=$false)]
    [switch]$DryRun
)

$hostname = "respondr.$Domain"

Write-Host "🚀 Complete Respondr Deployment" -ForegroundColor Green
Write-Host "======================================" -ForegroundColor Green
Write-Host "Resource Group: $ResourceGroupName" -ForegroundColor Cyan
Write-Host "Location: $Location" -ForegroundColor Cyan
Write-Host "Domain: $hostname" -ForegroundColor Cyan
Write-Host ""

# Function to check if command succeeded
function Test-LastCommand {
    param([string]$ErrorMessage)
    if ($LASTEXITCODE -ne 0) {
        Write-Error $ErrorMessage
        exit 1
    }
}

# Step 1: Infrastructure Deployment
if (-not $SkipInfrastructure) {
    Write-Host "📦 Step 1: Deploying Azure Infrastructure..." -ForegroundColor Yellow
    Write-Host "=============================================" -ForegroundColor Yellow
    
    if (-not $DryRun) {
        az deployment group create --resource-group $ResourceGroupName --template-file .\main.bicep
        Test-LastCommand "Infrastructure deployment failed"
        Write-Host "✅ Infrastructure deployed successfully" -ForegroundColor Green
    } else {
        Write-Host "DRY RUN: Would deploy infrastructure" -ForegroundColor Cyan
    }
} else {
    Write-Host "⏭️  Skipping infrastructure deployment" -ForegroundColor Yellow
}

# Step 2: Post-deployment Configuration
Write-Host "`n🔧 Step 2: Post-deployment Configuration..." -ForegroundColor Yellow
Write-Host "=============================================" -ForegroundColor Yellow

if (-not $DryRun) {
    .\post-deploy.ps1 -ResourceGroupName $ResourceGroupName -Location $Location
    Test-LastCommand "Post-deployment configuration failed"
    Write-Host "✅ Post-deployment configuration completed" -ForegroundColor Green
} else {
    Write-Host "DRY RUN: Would run post-deployment configuration" -ForegroundColor Cyan
}

# Step 3: HTTPS Certificate Setup
Write-Host "`n🔒 Step 3: Setting up HTTPS Certificate..." -ForegroundColor Yellow
Write-Host "=============================================" -ForegroundColor Yellow

# Get Application Gateway details
$deploy = az deployment group show --resource-group $ResourceGroupName --name main -o json | ConvertFrom-Json
$aksClusterName = $deploy.properties.outputs.aksClusterName.value
$appGwName = "$aksClusterName-appgw"
$mcResourceGroup = "MC_$($ResourceGroupName)_$($aksClusterName)_$($Location)"

Write-Host "Application Gateway: $appGwName" -ForegroundColor Cyan
Write-Host "MC Resource Group: $mcResourceGroup" -ForegroundColor Cyan

if (-not $DryRun) {
    # Check if HTTPS port exists
    $httpsPort = az network application-gateway frontend-port show --gateway-name $appGwName --resource-group $mcResourceGroup --name httpsPort 2>$null
    
    if (-not $httpsPort) {
        Write-Host "Adding HTTPS frontend port..." -ForegroundColor Yellow
        az network application-gateway frontend-port create `
            --gateway-name $appGwName `
            --resource-group $mcResourceGroup `
            --name httpsPort `
            --port 443
        Test-LastCommand "Failed to add HTTPS port"
        Write-Host "✅ HTTPS port added" -ForegroundColor Green
    } else {
        Write-Host "✅ HTTPS port already exists" -ForegroundColor Green
    }
    
    # Create self-signed certificate for testing
    Write-Host "Creating self-signed certificate for testing..." -ForegroundColor Yellow
    
    # Ensure temp directory exists
    $tempDir = "C:\temp"
    if (-not (Test-Path $tempDir)) {
        New-Item -ItemType Directory -Force -Path $tempDir | Out-Null
    }
    
    # Create certificate
    $cert = New-SelfSignedCertificate -DnsName $hostname -CertStoreLocation "cert:\LocalMachine\My"
    $pwd = ConvertTo-SecureString -String "TempPassword123!" -Force -AsPlainText
    $certPath = "$tempDir\respondr-cert.pfx"
    
    Export-PfxCertificate -Cert $cert -FilePath $certPath -Password $pwd | Out-Null
    
    # Upload to Application Gateway
    $existingCert = az network application-gateway ssl-cert show --gateway-name $appGwName --resource-group $mcResourceGroup --name respondr-ssl-cert 2>$null
    
    if (-not $existingCert) {
        Write-Host "Uploading SSL certificate to Application Gateway..." -ForegroundColor Yellow
        az network application-gateway ssl-cert create `
            --gateway-name $appGwName `
            --resource-group $mcResourceGroup `
            --name respondr-ssl-cert `
            --cert-file $certPath `
            --cert-password "TempPassword123!"
        Test-LastCommand "Failed to upload SSL certificate"
        Write-Host "✅ SSL certificate uploaded" -ForegroundColor Green
    } else {
        Write-Host "✅ SSL certificate already exists" -ForegroundColor Green
    }
    
    # Clean up certificate file
    Remove-Item $certPath -Force -ErrorAction SilentlyContinue
    
} else {
    Write-Host "DRY RUN: Would set up HTTPS certificate" -ForegroundColor Cyan
}

# Step 4: Application Deployment
Write-Host "`n🎯 Step 4: Deploying Application..." -ForegroundColor Yellow
Write-Host "=====================================" -ForegroundColor Yellow

$deployArgs = @(
    "-ResourceGroupName", $ResourceGroupName
    "-Namespace", "respondr"
)

if ($SkipImageBuild) {
    $deployArgs += "-SkipImageBuild"
}

if ($DryRun) {
    $deployArgs += "-DryRun"
}

if (-not $DryRun) {
    & .\deploy-to-k8s.ps1 @deployArgs
    Test-LastCommand "Application deployment failed"
    Write-Host "✅ Application deployed successfully" -ForegroundColor Green
} else {
    Write-Host "DRY RUN: Would deploy application" -ForegroundColor Cyan
}

# Step 5: DNS and Connectivity Verification
Write-Host "`n🌐 Step 5: DNS and Connectivity Verification..." -ForegroundColor Yellow
Write-Host "=================================================" -ForegroundColor Yellow

if (-not $DryRun) {
    # Get ingress IP
    Start-Sleep -Seconds 10  # Wait for ingress to be ready
    $ingressIp = kubectl get ingress respondr-ingress -n respondr -o jsonpath="{.status.loadBalancer.ingress[0].ip}" 2>$null
    
    if ($ingressIp) {
        Write-Host "Application Gateway IP: $ingressIp" -ForegroundColor Green
        
        # Test DNS resolution
        Write-Host "Testing DNS resolution..." -ForegroundColor Yellow
        try {
            $dnsResult = Resolve-DnsName -Name $hostname -ErrorAction Stop
            $resolvedIp = $dnsResult.IPAddress
            Write-Host "DNS resolves to: $resolvedIp" -ForegroundColor Green
            
            if ($resolvedIp -eq $ingressIp) {
                Write-Host "✅ DNS is correctly configured" -ForegroundColor Green
            } else {
                Write-Host "⚠️  DNS mismatch: Expected $ingressIp, got $resolvedIp" -ForegroundColor Yellow
                Write-Host "Please update your DNS A record:" -ForegroundColor Yellow
                Write-Host "  Type: A" -ForegroundColor Cyan
                Write-Host "  Name: respondr" -ForegroundColor Cyan
                Write-Host "  Value: $ingressIp" -ForegroundColor Cyan
            }
        } catch {
            Write-Host "❌ DNS resolution failed" -ForegroundColor Red
            Write-Host "Please add DNS A record:" -ForegroundColor Yellow
            Write-Host "  Type: A" -ForegroundColor Cyan
            Write-Host "  Name: respondr" -ForegroundColor Cyan
            Write-Host "  Value: $ingressIp" -ForegroundColor Cyan
        }
        
        # Test HTTP connectivity
        Write-Host "Testing HTTP connectivity..." -ForegroundColor Yellow
        try {
            $response = Invoke-WebRequest -Uri "http://$hostname/api/responders" -UseBasicParsing -TimeoutSec 10
            Write-Host "✅ HTTP connectivity successful (Status: $($response.StatusCode))" -ForegroundColor Green
        } catch {
            Write-Host "❌ HTTP connectivity failed: $($_.Exception.Message)" -ForegroundColor Red
        }
        
        # Test HTTPS connectivity
        Write-Host "Testing HTTPS connectivity..." -ForegroundColor Yellow
        try {
            $response = Invoke-WebRequest -Uri "https://$hostname/api/responders" -UseBasicParsing -TimeoutSec 10 -SkipCertificateCheck
            Write-Host "✅ HTTPS connectivity successful (Status: $($response.StatusCode))" -ForegroundColor Green
        } catch {
            Write-Host "❌ HTTPS connectivity failed: $($_.Exception.Message)" -ForegroundColor Red
            Write-Host "Note: HTTPS may take a few minutes to become available after certificate upload" -ForegroundColor Yellow
        }
    } else {
        Write-Host "❌ Could not get ingress IP address" -ForegroundColor Red
    }
} else {
    Write-Host "DRY RUN: Would verify DNS and connectivity" -ForegroundColor Cyan
}

# Summary
Write-Host "`n🎉 Deployment Summary" -ForegroundColor Green
Write-Host "=====================" -ForegroundColor Green

if (-not $DryRun) {
    Write-Host "✅ Infrastructure: Deployed" -ForegroundColor Green
    Write-Host "✅ AGIC & Authentication: Configured" -ForegroundColor Green
    Write-Host "✅ HTTPS Certificate: Self-signed (for testing)" -ForegroundColor Green
    Write-Host "✅ Application: Deployed to Kubernetes" -ForegroundColor Green
    Write-Host ""
    Write-Host "🌐 Access Information:" -ForegroundColor Cyan
    Write-Host "  HTTP:  http://$hostname" -ForegroundColor White
    Write-Host "  HTTPS: https://$hostname (may need a few minutes)" -ForegroundColor White
    Write-Host "  API:   https://$hostname/api/responders" -ForegroundColor White
    Write-Host ""
    Write-Host "🔐 Authentication:" -ForegroundColor Cyan
    Write-Host "  - Entra (Azure AD) authentication should redirect to Microsoft login" -ForegroundColor White
    Write-Host "  - If authentication doesn't work, configure via Azure Portal:" -ForegroundColor White
    Write-Host "    Application Gateway → Listeners → Add authentication" -ForegroundColor White
    Write-Host ""
    Write-Host "📝 Next Steps:" -ForegroundColor Cyan
    Write-Host "  1. Ensure DNS A record: respondr.$Domain → $ingressIp" -ForegroundColor White
    Write-Host "  2. Test in browser: https://$hostname" -ForegroundColor White
    Write-Host "  3. For production: Replace self-signed cert with real certificate" -ForegroundColor White
    Write-Host "  4. Verify Entra authentication redirects to Microsoft login" -ForegroundColor White
} else {
    Write-Host "DRY RUN completed - no changes made" -ForegroundColor Cyan
}

Write-Host ""
Write-Host "🚀 Deployment completed!" -ForegroundColor Green
