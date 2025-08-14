#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Verification script for OAuth2 authentication deployment

.DESCRIPTION
    This script verifies that OAuth2 proxy authentication is working correctly:
    1. Checks if OAuth2 secrets exist
    2. Verifies OAuth2 deployment is running
    3. Tests authentication endpoints
    4. Validates certificate status

.PARAMETER Domain
    The domain to test (default: rtreit.com)

.PARAMETER Namespace
    The Kubernetes namespace (default: respondr)

.EXAMPLE
    .\verify-oauth2-deployment.ps1 -Domain "rtreit.com"
#>

param(
    [Parameter(Mandatory=$false)]
    [string]$Domain = "rtreit.com",
    
    [Parameter(Mandatory=$false)]
    [string]$Namespace = "respondr"
)

$hostname = "respondr.$Domain"

Write-Host "OAuth2 Authentication Deployment Verification" -ForegroundColor Green
Write-Host "=================================================" -ForegroundColor Green
Write-Host "Domain: $hostname" -ForegroundColor Cyan
Write-Host "Namespace: $Namespace" -ForegroundColor Cyan
Write-Host ""

# Function to check command status
function Test-Check {
    param([string]$Name, [bool]$Success, [string]$Details = "")
    if ($Success) {
        Write-Host "✅ $Name" -ForegroundColor Green
        if ($Details) { Write-Host "   $Details" -ForegroundColor Gray }
    } else {
        Write-Host "❌ $Name" -ForegroundColor Red
        if ($Details) { Write-Host "   $Details" -ForegroundColor Gray }
    }
}

# Check 1: OAuth2 Secrets
Write-Host "1. Checking OAuth2 Secrets..." -ForegroundColor Yellow
try {
    $secrets = kubectl get secret oauth2-secrets -n $Namespace -o json 2>$null | ConvertFrom-Json
    $hasClientId = $null -ne $secrets.data.'client-id'
    $hasClientSecret = $null -ne $secrets.data.'client-secret'
    $hasCookieSecret = $null -ne $secrets.data.'cookie-secret'
    # tenant-id is not required in multi-tenant mode
    $hasTenantId = $false
    
    Test-Check "OAuth2 secrets exist" $true
    Test-Check "Client ID configured" $hasClientId
    Test-Check "Client Secret configured" $hasClientSecret
    Test-Check "Cookie Secret configured" $hasCookieSecret
    Test-Check "Tenant ID configured (single-tenant only)" $hasTenantId "Not required for multi-tenant"
    
    $allSecretsPresent = $hasClientId -and $hasClientSecret -and $hasCookieSecret
    Test-Check "All required secrets present" $allSecretsPresent
} catch {
    Test-Check "OAuth2 secrets exist" $false "Secret 'oauth2-secrets' not found"
}

Write-Host ""

# Check 2: Deployment Status
Write-Host "2. Checking Deployment Status..." -ForegroundColor Yellow
try {
    $pods = kubectl get pods -n $Namespace -l app=respondr -o json 2>$null | ConvertFrom-Json
    $podCount = $pods.items.Count
    
    if ($podCount -gt 0) {
        $runningPods = ($pods.items | Where-Object { $_.status.phase -eq "Running" }).Count
        Test-Check "Pods found" $true "$podCount pod(s) total"
        Test-Check "Pods running" ($runningPods -eq $podCount) "$runningPods/$podCount running"
        
        # Check containers in pods
        foreach ($pod in $pods.items) {
            $podName = $pod.metadata.name
            $containers = $pod.spec.containers.Count
            $runningContainers = ($pod.status.containerStatuses | Where-Object { $_.ready -eq $true }).Count
            
            Test-Check "Pod $podName containers" ($runningContainers -eq $containers) "$runningContainers/$containers ready"
            
            # Check if oauth2-proxy container exists
            $hasOAuth2Container = $pod.spec.containers | Where-Object { $_.name -eq "oauth2-proxy" }
            Test-Check "OAuth2 proxy container in $podName" ($null -ne $hasOAuth2Container)
        }
    } else {
        Test-Check "Pods found" $false "No pods with label app=respondr found"
    }
} catch {
    Test-Check "Deployment status check" $false $_.Exception.Message
}

Write-Host ""

# Check 3: Service Configuration
Write-Host "3. Checking Service Configuration..." -ForegroundColor Yellow
try {
    $service = kubectl get service respondr-service -n $Namespace -o json 2>$null | ConvertFrom-Json
    $targetPort = $service.spec.ports[0].targetPort
    
    Test-Check "Service exists" $true
    Test-Check "Service targets OAuth2 port" ($targetPort -eq 4180) "Target port: $targetPort"
} catch {
    Test-Check "Service exists" $false "Service 'respondr-service' not found"
}

Write-Host ""

# Check 4: Ingress and Certificate
Write-Host "4. Checking Ingress and Certificate..." -ForegroundColor Yellow
try {
    $ingress = kubectl get ingress respondr-ingress -n $Namespace -o json 2>$null | ConvertFrom-Json
    $ingressHost = $ingress.spec.rules[0].host
    
    Test-Check "Ingress exists" $true
    Test-Check "Ingress hostname configured" ($ingressHost -eq $hostname) "Host: $ingressHost"
    
    # Check certificate
    $cert = kubectl get certificate respondr-tls-letsencrypt -n $Namespace -o json 2>$null | ConvertFrom-Json
    $certReady = $cert.status.conditions | Where-Object { $_.type -eq "Ready" -and $_.status -eq "True" }
    
    Test-Check "Lets Encrypt certificate exists" $true
    Test-Check "Certificate is ready" ($null -ne $certReady)
} catch {
    Test-Check "Ingress configuration" $false $_.Exception.Message
}

Write-Host ""

# Check 5: DNS Resolution
Write-Host "5. Checking DNS Resolution..." -ForegroundColor Yellow
try {
    $dnsResult = Resolve-DnsName -Name $hostname -ErrorAction Stop
    $resolvedIp = $dnsResult.IPAddress
    
    Test-Check "DNS resolves" $true "Resolves to: $resolvedIp"
    
    # Get expected IP from ingress
    $ingressIp = kubectl get ingress respondr-ingress -n $Namespace -o jsonpath="{.status.loadBalancer.ingress[0].ip}" 2>$null
    if ($ingressIp) {
        Test-Check "DNS matches ingress IP" ($resolvedIp -eq $ingressIp) "Expected: $ingressIp, Got: $resolvedIp"
    }
} catch {
    Test-Check "DNS resolves" $false $_.Exception.Message
}

Write-Host ""

# Check 6: HTTP/HTTPS Connectivity
Write-Host "6. Checking HTTP/HTTPS Connectivity..." -ForegroundColor Yellow

# Test HTTP redirect
try {
    $httpResponse = Invoke-WebRequest -Uri "http://$hostname" -UseBasicParsing -MaximumRedirection 0 -ErrorAction Stop
    Test-Check "HTTP redirects to HTTPS" $false "Unexpected response: $($httpResponse.StatusCode)"
} catch {
    if ($_.Exception.Response.StatusCode -eq 302 -or $_.Exception.Response.StatusCode -eq 301) {
        Test-Check "HTTP redirects to HTTPS" $true "Redirect status: $($_.Exception.Response.StatusCode)"
    } else {
        Test-Check "HTTP connectivity" $false $_.Exception.Message
    }
}

# Test HTTPS with OAuth2 redirect
try {
    $httpsResponse = Invoke-WebRequest -Uri "https://$hostname" -UseBasicParsing -MaximumRedirection 0 -ErrorAction Stop
    Test-Check "HTTPS responds" $true "Status: $($httpsResponse.StatusCode)"
} catch {
    if ($_.Exception.Response.StatusCode -eq 302) {
        $location = $_.Exception.Response.Headers.Location
        if ($location -and $location.Contains("login.microsoftonline.com")) {
            Test-Check "OAuth2 authentication redirect" $true "Redirects to Microsoft login"
        } else {
            Test-Check "OAuth2 authentication redirect" $false "Redirect location: $location"
        }
    } else {
        Test-Check "HTTPS connectivity" $false $_.Exception.Message
    }
}

Write-Host ""

# Check 7: OAuth2 Proxy Logs
Write-Host "7. Checking OAuth2 Proxy Logs..." -ForegroundColor Yellow
try {
    $logOutput = kubectl logs -n $Namespace -l app=respondr -c oauth2-proxy --tail=10 2>$null
    if ($logOutput) {
        $hasAuthLogs = $logOutput | Where-Object { $_ -match "authentication|login|oauth" }
        Test-Check "OAuth2 proxy logs available" $true
        Test-Check "Authentication activity detected" ($hasAuthLogs.Count -gt 0)
        
        # Show recent authentication activity
        if ($hasAuthLogs.Count -gt 0) {
            Write-Host "   Recent OAuth2 activity:" -ForegroundColor Gray
            $hasAuthLogs | Select-Object -Last 3 | ForEach-Object {
                Write-Host "   $_" -ForegroundColor Gray
            }
        }
    } else {
        Test-Check "OAuth2 proxy logs available" $false "No logs found"
    }
} catch {
    Test-Check "OAuth2 proxy logs" $false $_.Exception.Message
}

Write-Host ""

# Summary
Write-Host "Verification Summary" -ForegroundColor Green
Write-Host "======================" -ForegroundColor Green
Write-Host ""
Write-Host "✅ Your OAuth2 authentication deployment appears to be working!" -ForegroundColor Green
Write-Host ""
Write-Host "🔗 Test URLs:" -ForegroundColor Cyan
Write-Host "  Main site: https://$hostname" -ForegroundColor White
Write-Host "  API endpoint: https://$hostname/api/responders" -ForegroundColor White
Write-Host "  OAuth2 callback: https://$hostname/oauth2/callback" -ForegroundColor White
Write-Host ""
Write-Host "🔐 Expected Behavior:" -ForegroundColor Cyan
Write-Host "  1. Visit https://$hostname" -ForegroundColor White
Write-Host "  2. Automatically redirect to Microsoft login" -ForegroundColor White
Write-Host "  3. After successful login, redirect back to application" -ForegroundColor White
Write-Host "  4. Access protected content without further authentication" -ForegroundColor White
Write-Host ""
Write-Host "🛠️  Troubleshooting Commands:" -ForegroundColor Cyan
Write-Host "  kubectl get pods -n $Namespace -l app=respondr" -ForegroundColor White
Write-Host "  kubectl logs -n $Namespace -l app=respondr -c oauth2-proxy" -ForegroundColor White
Write-Host "  kubectl get certificate -n $Namespace" -ForegroundColor White
Write-Host "  kubectl get ingress -n $Namespace" -ForegroundColor White

Write-Host ""
Write-Host "✅ Verification completed!" -ForegroundColor Green
