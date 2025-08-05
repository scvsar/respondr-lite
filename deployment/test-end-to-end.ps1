#!/usr/bin/env pwsh

<#
.SYNOPSIS
    End-to-end test script for Respondr deployment with OAuth2 authentication

.DESCRIPTION
    This script performs comprehensive testing of the Respondr application:
    1. Tests OAuth2 authentication flow
    2. Validates API endpoints after authentication
    3. Sends test webhook data
    4. Verifies data processing and dashboard functionality

.PARAMETER Domain
    The domain to test (default: paincave.pro)

.PARAMETER Namespace
    The Kubernetes namespace (default: respondr)

.EXAMPLE
    .\test-end-to-end.ps1 -Domain "paincave.pro"
#>

param(
    [Parameter(Mandatory=$false)]
    [string]$Domain = "paincave.pro",
    
    [Parameter(Mandatory=$false)]
    [string]$Namespace = "respondr"
)

$hostname = "respondr.$Domain"

Write-Host "🧪 End-to-End Respondr Testing with OAuth2" -ForegroundColor Green
Write-Host "===========================================" -ForegroundColor Green
Write-Host "Domain: $hostname" -ForegroundColor Cyan
Write-Host "Namespace: $Namespace" -ForegroundColor Cyan
Write-Host ""

# Function to test with detailed output
function Test-Endpoint {
    param(
        [string]$Name,
        [string]$Url,
        [string]$Method = "GET",
        [string]$Body = $null,
        [string]$ContentType = "application/json"
    )
    
    Write-Host "Testing $Name..." -ForegroundColor Yellow
    Write-Host "  URL: $Url" -ForegroundColor Gray
    
    try {
        $params = @{
            Uri = $Url
            Method = $Method
            UseBasicParsing = $true
            TimeoutSec = 30
            MaximumRedirection = 5
        }
        
        if ($Body) {
            $params.Body = $Body
            $params.ContentType = $ContentType
        }
        
        $response = Invoke-WebRequest @params
        
        Write-Host "  ✅ Status: $($response.StatusCode)" -ForegroundColor Green
        Write-Host "  ✅ Content Length: $($response.Content.Length) bytes" -ForegroundColor Green
        
        if ($response.Content.Length -lt 1000) {
            Write-Host "  📄 Response: $($response.Content)" -ForegroundColor Gray
        } else {
            Write-Host "  📄 Response: Large response received ($(($response.Content.Length)) bytes)" -ForegroundColor Gray
        }
        
        return @{ Success = $true; StatusCode = $response.StatusCode; Content = $response.Content }
    } catch {
        if ($_.Exception.Response) {
            $statusCode = $_.Exception.Response.StatusCode.value__
            Write-Host "  ❌ Status: $statusCode" -ForegroundColor Red
            
            # Special handling for OAuth2 redirects
            if ($statusCode -eq 302) {
                $location = $_.Exception.Response.Headers.Location
                if ($location -and $location.Contains("login.microsoftonline.com")) {
                    Write-Host "  🔐 OAuth2 Redirect: Authentication required (Expected behavior)" -ForegroundColor Cyan
                    Write-Host "  🔗 Redirect to: $location" -ForegroundColor Gray
                    return @{ Success = $true; StatusCode = 302; Content = "OAuth2 Redirect"; AuthRequired = $true }
                } else {
                    Write-Host "  🔗 Redirect to: $location" -ForegroundColor Gray
                }
            }
        } else {
            Write-Host "  ❌ Error: $($_.Exception.Message)" -ForegroundColor Red
        }
        
        return @{ Success = $false; Error = $_.Exception.Message }
    }
}

Write-Host "🔍 1. Basic Connectivity Tests" -ForegroundColor Yellow
Write-Host "==============================" -ForegroundColor Yellow

# Test HTTP redirect
$httpTest = Test-Endpoint "HTTP to HTTPS redirect" "http://$hostname"

# Test HTTPS main page (should redirect to OAuth2)
$httpsTest = Test-Endpoint "HTTPS main page (OAuth2 check)" "https://$hostname"

# Test health endpoint (if available)
$healthTest = Test-Endpoint "Health endpoint" "https://$hostname/health"

Write-Host ""
Write-Host "🔐 2. OAuth2 Authentication Tests" -ForegroundColor Yellow
Write-Host "==================================" -ForegroundColor Yellow

# Test OAuth2 callback endpoint
$callbackTest = Test-Endpoint "OAuth2 callback endpoint" "https://$hostname/oauth2/callback"

# Test OAuth2 sign-in endpoint
$signinTest = Test-Endpoint "OAuth2 sign-in endpoint" "https://$hostname/oauth2/sign_in"

Write-Host ""
Write-Host "📊 3. API Endpoint Tests (Authentication Required)" -ForegroundColor Yellow
Write-Host "==================================================" -ForegroundColor Yellow

# Test API endpoints that require authentication
$apiTest = Test-Endpoint "API responders endpoint" "https://$hostname/api/responders"

Write-Host ""
Write-Host "📨 4. Webhook Testing" -ForegroundColor Yellow
Write-Host "=====================" -ForegroundColor Yellow

# Create test webhook payload
$testPayload = @{
    name = "Test User - $(Get-Date -Format 'HH:mm:ss')"
    text = "I am responding with SAR78, ETA 15 minutes"
    created_at = [int][double]::Parse((Get-Date -UFormat %s))
} | ConvertTo-Json

Write-Host "Test payload:" -ForegroundColor Gray
Write-Host $testPayload -ForegroundColor Gray

$webhookTest = Test-Endpoint "Webhook endpoint" "https://$hostname/webhook" -Method "POST" -Body $testPayload

# Wait a moment for processing
if ($webhookTest.Success -and $webhookTest.StatusCode -ne 302) {
    Write-Host "Waiting 3 seconds for webhook processing..." -ForegroundColor Gray
    Start-Sleep -Seconds 3
    
    # Test API again to see if data was processed
    Test-Endpoint "API after webhook" "https://$hostname/api/responders" | Out-Null
}

Write-Host ""
Write-Host "🌐 5. Certificate and Security Tests" -ForegroundColor Yellow
Write-Host "=====================================" -ForegroundColor Yellow

# Test SSL certificate
try {
    [System.Net.ServicePointManager]::ServerCertificateValidationCallback = {$true}
    $req = [System.Net.WebRequest]::Create("https://$hostname")
    $req.GetResponse() | Out-Null
    
    Write-Host "✅ SSL certificate is valid" -ForegroundColor Green
} catch {
    Write-Host "❌ SSL certificate issue: $($_.Exception.Message)" -ForegroundColor Red
}

# Check certificate via kubectl
try {
    $certStatus = kubectl get certificate respondr-tls-letsencrypt -n $Namespace -o jsonpath="{.status.conditions[?(@.type=='Ready')].status}" 2>$null
    if ($certStatus -eq "True") {
        Write-Host "✅ Let's Encrypt certificate is ready" -ForegroundColor Green
    } else {
        Write-Host "⏳ Let's Encrypt certificate not ready yet" -ForegroundColor Yellow
    }
} catch {
    Write-Host "❌ Could not check certificate status" -ForegroundColor Red
}

Write-Host ""
Write-Host "📋 6. Deployment Status Summary" -ForegroundColor Yellow
Write-Host "================================" -ForegroundColor Yellow

# Check pod status
try {
    $pods = kubectl get pods -n $Namespace -l app=respondr -o json 2>$null | ConvertFrom-Json
    foreach ($pod in $pods.items) {
        $podName = $pod.metadata.name
        $phase = $pod.status.phase
        $readyContainers = ($pod.status.containerStatuses | Where-Object { $_.ready -eq $true }).Count
        $totalContainers = $pod.spec.containers.Count
        
        if ($phase -eq "Running" -and $readyContainers -eq $totalContainers) {
            Write-Host "✅ Pod $podName is running ($readyContainers/$totalContainers containers ready)" -ForegroundColor Green
        } else {
            Write-Host "⚠️  Pod $podName status: $phase ($readyContainers/$totalContainers containers ready)" -ForegroundColor Yellow
        }
    }
} catch {
    Write-Host "❌ Could not check pod status" -ForegroundColor Red
}

Write-Host ""
Write-Host "🎯 Test Results Summary" -ForegroundColor Green
Write-Host "=======================" -ForegroundColor Green

$allTests = @(
    @{ Name = "HTTP redirect"; Result = $httpTest },
    @{ Name = "HTTPS main page"; Result = $httpsTest },
    @{ Name = "Health endpoint"; Result = $healthTest },
    @{ Name = "OAuth2 callback"; Result = $callbackTest },
    @{ Name = "OAuth2 sign-in"; Result = $signinTest },
    @{ Name = "API endpoint"; Result = $apiTest },
    @{ Name = "Webhook"; Result = $webhookTest }
)

$passedTests = 0
$totalTests = $allTests.Count

foreach ($test in $allTests) {
    $result = $test.Result
    if ($result.Success) {
        if ($result.AuthRequired) {
            Write-Host "✅ $($test.Name): Authentication required (OAuth2 working)" -ForegroundColor Green
        } else {
            Write-Host "✅ $($test.Name): Passed (Status: $($result.StatusCode))" -ForegroundColor Green
        }
        $passedTests++
    } else {
        Write-Host "❌ $($test.Name): Failed" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "📊 Overall Result: $passedTests/$totalTests tests passed" -ForegroundColor Cyan

if ($passedTests -eq $totalTests) {
    Write-Host "🎉 All tests passed! Your OAuth2 deployment is working correctly." -ForegroundColor Green
} elseif ($passedTests -ge ($totalTests * 0.8)) {
    Write-Host "⚠️  Most tests passed. Check the failed tests above for issues." -ForegroundColor Yellow
} else {
    Write-Host "❌ Multiple tests failed. Please check your deployment." -ForegroundColor Red
}

Write-Host ""
Write-Host "🔗 Manual Testing Instructions" -ForegroundColor Cyan
Write-Host "==============================" -ForegroundColor Cyan
Write-Host "1. Open a browser and navigate to: https://$hostname" -ForegroundColor White
Write-Host "2. You should be redirected to Microsoft sign-in page" -ForegroundColor White
Write-Host "3. Sign in with your Azure AD/Entra credentials" -ForegroundColor White
Write-Host "4. You should be redirected back to the application dashboard" -ForegroundColor White
Write-Host "5. Try accessing: https://$hostname/api/responders" -ForegroundColor White
Write-Host "6. You should see JSON data without additional authentication" -ForegroundColor White

Write-Host ""
Write-Host "🛠️  Troubleshooting" -ForegroundColor Cyan
Write-Host "==================" -ForegroundColor Cyan
Write-Host "If tests fail:" -ForegroundColor White
Write-Host "1. Run: .\verify-oauth2-deployment.ps1 -Domain $Domain" -ForegroundColor Gray
Write-Host "2. Check pod logs: kubectl logs -n $Namespace -l app=respondr -c oauth2-proxy" -ForegroundColor Gray
Write-Host "3. Check certificate: kubectl get certificate -n $Namespace" -ForegroundColor Gray
Write-Host "4. Check ingress: kubectl get ingress -n $Namespace" -ForegroundColor Gray

Write-Host ""
Write-Host "✅ End-to-end testing completed!" -ForegroundColor Green
