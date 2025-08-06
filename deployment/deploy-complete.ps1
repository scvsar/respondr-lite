#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Complete end-to-end deployment script for Respondr application with HTTPS and Entra authentication.

.DESCRIPTION
    This script performs the complete deployment workflow:
    1. Infrastructure deployment (Bicep)
    2. Post-deployment configuration (AGIC, identities, auth setup)
    3. OAuth2 authentication setup (Azure AD app registration and configuration)
    4. HTTPS certificate configuration
    5. Application deployment to Kubernetes with OAuth2 proxy
    6. DNS verification and testing

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

.PARAMETER UseOAuth2
    Use OAuth2 proxy for authentication (default: true). If false, uses Application Gateway authentication.

.EXAMPLE
    .\deploy-complete.ps1 -ResourceGroupName "respondr" -Domain "paincave.pro"
    
.EXAMPLE
    .\deploy-complete.ps1 -ResourceGroupName "respondr" -Domain "paincave.pro" -UseOAuth2:$false
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
    [switch]$UseOAuth2 = $true,  # Default to OAuth2 authentication
    
    [Parameter(Mandatory=$false)]
    [switch]$DryRun
)

$hostname = "respondr.$Domain"

Write-Host "Complete Respondr Deployment" -ForegroundColor Green
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
        Write-Host "Infrastructure deployed successfully" -ForegroundColor Green
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
    Write-Host "Post-deployment configuration completed" -ForegroundColor Green
} else {
    Write-Host "DRY RUN: Would run post-deployment configuration" -ForegroundColor Cyan
}

# Step 3: Let's Encrypt Certificate Setup
Write-Host "`n🔒 Step 3: Setting up Let's Encrypt Certificates..." -ForegroundColor Yellow
Write-Host "=================================================" -ForegroundColor Yellow

# Get Application Gateway details
$deploy = az deployment group show --resource-group $ResourceGroupName --name main -o json | ConvertFrom-Json
$aksClusterName = $deploy.properties.outputs.aksClusterName.value
$mcResourceGroup = "MC_$($ResourceGroupName)_$($aksClusterName)_$($Location)"

# Get the actual Application Gateway name from AGIC configuration
Write-Host "Getting Application Gateway name from AGIC configuration..." -ForegroundColor Yellow
$agicConfig = az aks show --resource-group $ResourceGroupName --name $aksClusterName --query "addonProfiles.ingressApplicationGateway.config.effectiveApplicationGatewayId" -o tsv 2>$null

if ($agicConfig) {
    # Extract the Application Gateway name from the resource ID
    $appGwName = $agicConfig.Split('/')[-1]
    Write-Host "Found Application Gateway: $appGwName" -ForegroundColor Green
} else {
    # Fallback to the expected name pattern
    $appGwName = "$aksClusterName-appgw"
    Write-Host "Could not get Application Gateway from AGIC - using fallback name: $appGwName" -ForegroundColor Yellow
}

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
        Write-Host "HTTPS port added" -ForegroundColor Green
    } else {
        Write-Host "HTTPS port already exists" -ForegroundColor Green
    }
    
    Write-Host "Application Gateway configured for HTTPS - Let's Encrypt certificates will be managed by cert-manager" -ForegroundColor Green
    Write-Host "Note: SSL certificates will be automatically provisioned when the ingress is deployed" -ForegroundColor Yellow
    
} else {
    Write-Host "DRY RUN: Would configure Application Gateway for HTTPS with Let's Encrypt" -ForegroundColor Cyan
}

# Step 4: OAuth2 Authentication Setup
if ($UseOAuth2) {
    Write-Host "`n🔐 Step 4: Setting up OAuth2 Authentication..." -ForegroundColor Yellow
    Write-Host "===============================================" -ForegroundColor Yellow

    if (-not $DryRun) {
        .\setup-oauth2.ps1 -ResourceGroupName $ResourceGroupName -Domain $Domain
        Test-LastCommand "OAuth2 authentication setup failed"
        Write-Host "OAuth2 authentication configured successfully" -ForegroundColor Green
    } else {
        Write-Host "DRY RUN: Would setup OAuth2 authentication" -ForegroundColor Cyan
    }
} else {
    Write-Host "`n⏭️  Step 4: Skipping OAuth2 Authentication (using Application Gateway auth)" -ForegroundColor Yellow
    Write-Host "============================================================================" -ForegroundColor Yellow
}

# Step 5: DNS Configuration Check and Prompt
Write-Host "`n🌐 Step 5: DNS Configuration Verification..." -ForegroundColor Yellow
Write-Host "=============================================" -ForegroundColor Yellow

if (-not $DryRun) {
    # Get the Application Gateway IP
    $appGwIp = az network public-ip show --resource-group $mcResourceGroup --name "applicationgateway-appgwpip" --query "ipAddress" -o tsv 2>$null
    
    if ($appGwIp) {
        Write-Host "Your Application Gateway IP is: $appGwIp" -ForegroundColor Green
        Write-Host ""
        Write-Host "REQUIRED DNS CONFIGURATION:" -ForegroundColor Red
        Write-Host "Before continuing, you MUST configure DNS:" -ForegroundColor Yellow
        Write-Host "  1. Add an A record in your $Domain DNS zone:" -ForegroundColor Cyan
        Write-Host "     Name: respondr" -ForegroundColor White
        Write-Host "     Type: A" -ForegroundColor White
        Write-Host "     Value: $appGwIp" -ForegroundColor White
        Write-Host "     TTL: 300" -ForegroundColor White
        Write-Host ""
        Write-Host "  2. Wait for DNS propagation (usually 1-5 minutes)" -ForegroundColor Cyan
        Write-Host "  3. Test with: nslookup respondr.$Domain" -ForegroundColor Cyan
        Write-Host ""
        
        # Test current DNS resolution
        Write-Host "Testing current DNS resolution..." -ForegroundColor Yellow
        try {
            $dnsResult = Resolve-DnsName -Name $hostname -ErrorAction Stop
            $resolvedIp = $dnsResult.IPAddress
            Write-Host "DNS currently resolves to: $resolvedIp" -ForegroundColor Green
            
            if ($resolvedIp -eq $appGwIp) {
                Write-Host "✅ DNS is correctly configured!" -ForegroundColor Green
            } else {
                Write-Host "❌ DNS mismatch: Expected $appGwIp, got $resolvedIp" -ForegroundColor Red
                Write-Host "Please update your DNS A record and wait for propagation." -ForegroundColor Yellow
            }
        } catch {
            Write-Host "❌ DNS resolution failed - $hostname does not resolve" -ForegroundColor Red
            Write-Host "Please add the DNS A record as shown above." -ForegroundColor Yellow
        }
        
        Write-Host ""
        Write-Host "Press ENTER to continue once DNS is configured, or Ctrl+C to abort..." -ForegroundColor Yellow
        Read-Host
        
        # Verify DNS again after user confirmation
        Write-Host "Verifying DNS configuration..." -ForegroundColor Yellow
        try {
            $dnsResult = Resolve-DnsName -Name $hostname -ErrorAction Stop
            $resolvedIp = $dnsResult.IPAddress
            
            if ($resolvedIp -eq $appGwIp) {
                Write-Host "✅ DNS verification successful!" -ForegroundColor Green
            } else {
                Write-Host "⚠️  DNS still shows mismatch but continuing..." -ForegroundColor Yellow
                Write-Host "Expected: $appGwIp, Got: $resolvedIp" -ForegroundColor Yellow
            }
        } catch {
            Write-Host "⚠️  DNS still not resolving but continuing..." -ForegroundColor Yellow
        }
    } else {
        Write-Host "❌ Could not retrieve Application Gateway IP" -ForegroundColor Red
    }
} else {
    Write-Host "DRY RUN: Would verify DNS configuration" -ForegroundColor Cyan
}

# Step 6: Secrets Creation
Write-Host "`n🔑 Step 6: Creating Application Secrets..." -ForegroundColor Yellow
Write-Host "===========================================" -ForegroundColor Yellow

if (-not $DryRun) {
    # Create secrets using the dedicated script
    Write-Host "Generating application secrets..." -ForegroundColor Yellow
    .\create-secrets.ps1 -ResourceGroupName $ResourceGroupName
    Test-LastCommand "Secrets creation failed"
    Write-Host "Application secrets created successfully" -ForegroundColor Green
} else {
    Write-Host "DRY RUN: Would create application secrets" -ForegroundColor Cyan
}

# Step 7: Application Deployment
Write-Host "`n📦 Step 7: Deploying Application with Authentication..." -ForegroundColor Yellow
Write-Host "======================================================" -ForegroundColor Yellow

$deployArgs = @(
    "-ResourceGroupName", $ResourceGroupName
    "-Namespace", "respondr"
)

if ($UseOAuth2) {
    $deployArgs += "-UseOAuth2"
}

if ($SkipImageBuild) {
    $deployArgs += "-SkipImageBuild"
}

if ($DryRun) {
    $deployArgs += "-DryRun"
}

if (-not $DryRun) {
    & .\deploy-to-k8s.ps1 @deployArgs
    Test-LastCommand "Application deployment failed"
    Write-Host "Application with OAuth2 authentication deployed successfully" -ForegroundColor Green
    
    # Sync local .env file with Kubernetes secrets for development
    Write-Host "Syncing local .env file with deployed secrets..." -ForegroundColor Yellow
    .\sync-env.ps1
    Write-Host "Local .env file updated for development use" -ForegroundColor Green
} else {
    Write-Host "DRY RUN: Would deploy application with OAuth2 authentication" -ForegroundColor Cyan
}

# Step 8: DNS and Connectivity Verification
Write-Host "`n🌐 Step 8: DNS and Connectivity Verification..." -ForegroundColor Yellow
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
                Write-Host "DNS is correctly configured" -ForegroundColor Green
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
            Write-Host "HTTP connectivity successful (Status: $($response.StatusCode))" -ForegroundColor Green
        } catch {
            Write-Host "❌ HTTP connectivity failed: $($_.Exception.Message)" -ForegroundColor Red
        }
        
        # Test HTTPS connectivity
        Write-Host "Testing HTTPS connectivity..." -ForegroundColor Yellow
        try {
            $response = Invoke-WebRequest -Uri "https://$hostname/api/responders" -UseBasicParsing -TimeoutSec 10 -SkipCertificateCheck
            Write-Host "HTTPS connectivity successful (Status: $($response.StatusCode))" -ForegroundColor Green
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
Write-Host "`nDeployment Summary" -ForegroundColor Green
Write-Host "=====================" -ForegroundColor Green

if (-not $DryRun) {
    Write-Host "Infrastructure: Deployed" -ForegroundColor Green
    Write-Host "AGIC & Authentication: Configured" -ForegroundColor Green
    Write-Host "Let's Encrypt Setup: Configured via cert-manager" -ForegroundColor Green
    Write-Host "OAuth2 Authentication: Configured with Azure AD" -ForegroundColor Green
    Write-Host "Application: Deployed to Kubernetes with OAuth2 proxy" -ForegroundColor Green
    Write-Host ""
    Write-Host "🌐 Access Information:" -ForegroundColor Cyan
    Write-Host "  HTTP:  http://$hostname (redirects to HTTPS)" -ForegroundColor White
    Write-Host "  HTTPS: https://$hostname" -ForegroundColor White
    Write-Host "  API:   https://$hostname/api/responders" -ForegroundColor White
    Write-Host ""
    Write-Host "🔐 Authentication:" -ForegroundColor Cyan
    Write-Host "  - OAuth2 Proxy with Azure AD authentication is ENABLED" -ForegroundColor White
    Write-Host "  - Users WILL be challenged to sign in with Entra/Azure AD" -ForegroundColor White
    Write-Host "  - Authentication is handled by oauth2-proxy sidecar container" -ForegroundColor White
    Write-Host "  - No application code changes required" -ForegroundColor White
    Write-Host ""
    Write-Host "🔒 SSL Certificates:" -ForegroundColor Cyan
    Write-Host "  - Let's Encrypt certificates will be automatically provisioned" -ForegroundColor White
    Write-Host "  - Initial certificate request may take a few minutes" -ForegroundColor White
    Write-Host "  - Check certificate status: kubectl get certificate -n respondr" -ForegroundColor White
    Write-Host ""
    Write-Host "📝 Next Steps:" -ForegroundColor Cyan
    Write-Host "  1. Ensure DNS A record: respondr.$Domain → $ingressIp" -ForegroundColor White
    Write-Host "  2. Wait for Let's Encrypt certificate to be issued (2-10 minutes)" -ForegroundColor White
    Write-Host "  3. Test in browser: https://$hostname" -ForegroundColor White
    Write-Host "  4. Verify OAuth2 authentication redirects to Microsoft sign-in" -ForegroundColor White
    Write-Host "  5. Test API access after authentication: https://$hostname/api/responders" -ForegroundColor White
    Write-Host ""
    Write-Host "Certificate Status Commands:" -ForegroundColor Cyan
    Write-Host "  kubectl get certificate -n respondr" -ForegroundColor White
    Write-Host "  kubectl describe certificate respondr-tls-letsencrypt -n respondr" -ForegroundColor White
    Write-Host "  kubectl get certificaterequests -n respondr" -ForegroundColor White
} else {
    Write-Host "DRY RUN completed - no changes made" -ForegroundColor Cyan
}

Write-Host ""
Write-Host "Deployment completed!" -ForegroundColor Green
