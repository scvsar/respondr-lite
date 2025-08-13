# OAuth2 Proxy Setup Script for Azure AD Integration
# This script creates an Azure AD app registration and configures oauth2-proxy for Entra authentication

param(
    [Parameter(Mandatory=$true)]
    [string]$ResourceGroupName,
    
    [Parameter(Mandatory=$false)]
    [string]$Domain = "paincave.pro",
    
    [Parameter(Mandatory=$false)]
    [string]$AppName = "respondr-oauth2",

    [Parameter(Mandatory=$false)]
    [string]$Namespace = "respondr",

    [Parameter(Mandatory=$false)]
    [string]$HostPrefix = "respondr"
,
    # Optional: In certain Microsoft-owned tenants (SFI), app creation requires a Service Tree ID
    # Do NOT hardcode this value; pass it via -ServiceTreeId when running the script
    [Parameter(Mandatory=$false)]
    [string]$ServiceTreeId
)

Write-Host "Setting up OAuth2 Proxy with Azure AD integration..." -ForegroundColor Green
Write-Host "Resource Group: $ResourceGroupName" -ForegroundColor Cyan
Write-Host "Domain: $Domain" -ForegroundColor Cyan

# Get tenant ID
$tenantId = az account show --query tenantId -o tsv
if (-not $tenantId) {
    Write-Error "Failed to get tenant ID. Make sure you're logged into Azure CLI."
    exit 1
}

if (-not $HostPrefix -or $HostPrefix -eq "") { $HostPrefix = "respondr" }
$redirectUri = "https://$HostPrefix.$Domain/oauth2/callback"
$hostname = "$HostPrefix.$Domain"

Write-Host "Tenant ID: $tenantId" -ForegroundColor Cyan
Write-Host "Redirect URI: $redirectUri" -ForegroundColor Cyan

# Helper: Invoke Microsoft Graph via az rest and return JSON
function Invoke-Graph {
    param(
        [Parameter(Mandatory=$true)][string]$Method,
        [Parameter(Mandatory=$true)][string]$Url,
        [Parameter(Mandatory=$false)]$Body
    )
    $tempFile = $null
    try {
        # Acquire MS Graph token (cache per session)
        if (-not $script:GraphAccessToken) {
            $token = az account get-access-token --resource-type ms-graph --query accessToken -o tsv 2>$null
            if (-not $token) {
                $token = az account get-access-token --resource https://graph.microsoft.com/ --query accessToken -o tsv 2>$null
            }
            if (-not $token) { throw "Failed to acquire Microsoft Graph access token via Azure CLI" }
            $script:GraphAccessToken = $token
        }

    $headersJson = @{ Authorization = ("Bearer {0}" -f $script:GraphAccessToken); 'Content-Type' = 'application/json'; Accept = 'application/json' } | ConvertTo-Json -Compress
    $args = @('--method', $Method, '--url', $Url, '--headers', $headersJson)
        if ($null -ne $Body) {
            if ($Body -is [string]) {
                $jsonBody = $Body
                $args += @('--body', $jsonBody)
            } else {
                $jsonBody = ($Body | ConvertTo-Json -Depth 20 -Compress)
                $tempFile = Join-Path $env:TEMP ("graph_body_{0}.json" -f ([guid]::NewGuid()))
                Set-Content -Path $tempFile -Value $jsonBody -Encoding UTF8 -NoNewline
                $args += @('--body', '@' + $tempFile)
            }
        }
        $raw = az rest @args -o json 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Warning ("Microsoft Graph call failed ({0} {1}): {2}" -f $Method, $Url, ($raw -join "`n"))
            return $null
        }
        if ($raw) {
            try { return ($raw | ConvertFrom-Json) } catch { return $null }
        } else { return $null }
    } finally {
        if ($tempFile -and (Test-Path $tempFile)) { Remove-Item -Path $tempFile -ErrorAction SilentlyContinue }
    }
}

# Use Microsoft Graph for app discovery/creation to support Service Tree enforcement (MSIT/SFI tenants)
Write-Host "Checking for existing app registration (Microsoft Graph)..." -ForegroundColor Yellow
$filterExpr = "displayName eq '$AppName'"
$listUrl = "https://graph.microsoft.com/v1.0/applications?`$filter=" + ([uri]::EscapeDataString($filterExpr))
$listResult = Invoke-Graph -Method GET -Url $listUrl
$existingApp = $null
if ($listResult -and $listResult.value -and $listResult.value.Count -gt 0) {
    $existingApp = $listResult.value[0]
} elseif (-not $listResult) {
    # Try beta as a fallback
    $listUrlBeta = "https://graph.microsoft.com/beta/applications?`$filter=" + ([uri]::EscapeDataString($filterExpr))
    $listResult = Invoke-Graph -Method GET -Url $listUrlBeta
    if ($listResult -and $listResult.value -and $listResult.value.Count -gt 0) {
        $existingApp = $listResult.value[0]
    }
}

if ($existingApp) {
    Write-Host "Found existing app registration: $($existingApp.displayName)" -ForegroundColor Green
    $graphAppId = $existingApp.id
    $appId = $existingApp.appId

    # Merge redirect URIs and set multi-tenant; optionally update Service Tree ref
    Write-Host "Updating app to multi-tenant and ensuring redirect URI exists..." -ForegroundColor Yellow
    $existingUris = @()
    try { $existingUris = @($existingApp.web.redirectUris) } catch { $existingUris = @() }
    if (-not ($existingUris -contains $redirectUri)) {
        $newUris = @($existingUris + @($redirectUri) | Where-Object { $_ } | Select-Object -Unique)
    } else {
        $newUris = $existingUris
    }
    $patchBody = @{ signInAudience = 'AzureADMultipleOrgs'; web = @{ redirectUris = @($newUris) } }
    if ($ServiceTreeId) { $patchBody.serviceManagementReference = $ServiceTreeId }
    $patch = Invoke-Graph -Method PATCH -Url "https://graph.microsoft.com/v1.0/applications/$graphAppId" -Body $patchBody
    if ($null -eq $patch) {
        # Fallback to beta endpoint if v1.0 rejects fields
        $patch = Invoke-Graph -Method PATCH -Url "https://graph.microsoft.com/beta/applications/$graphAppId" -Body $patchBody
        if ($null -eq $patch) { Write-Host "Patch request completed (no content returned) or failed; proceeding idempotently" -ForegroundColor Yellow }
    }
} else {
    # Create new app registration via Microsoft Graph to include Service Tree ID when provided
    Write-Host "Creating new Azure AD app registration (Microsoft Graph)..." -ForegroundColor Yellow
    $createBody = @{ displayName = $AppName; signInAudience = 'AzureADMultipleOrgs'; web = @{ redirectUris = @($redirectUri) } }
    if ($ServiceTreeId) { $createBody.serviceManagementReference = $ServiceTreeId }
    $created = Invoke-Graph -Method POST -Url 'https://graph.microsoft.com/v1.0/applications' -Body $createBody
    if (-not $created) {
        # Fallback to beta endpoint if v1.0 rejects fields (e.g., serviceManagementReference)
        $created = Invoke-Graph -Method POST -Url 'https://graph.microsoft.com/beta/applications' -Body $createBody
        if (-not $created) {
            Write-Error "Failed to create app registration"
            exit 1
        }
    }
    $graphAppId = $created.id
    $appId = $created.appId
    Write-Host "Created app registration with ID: $appId" -ForegroundColor Green
}

# Create/reset client secret
Write-Host "Creating client secret..." -ForegroundColor Yellow
$clientSecret = az ad app credential reset --id $appId --append --query password -o tsv 2>$null
if (-not $clientSecret -or $LASTEXITCODE -ne 0) {
    Write-Warning "az ad app credential reset failed or returned empty. Falling back to Microsoft Graph addPassword API."
    $end = (Get-Date).AddYears(2).ToUniversalTime().ToString('o')
    $pwdBody = @{ passwordCredential = @{ displayName = "$AppName-secret"; endDateTime = $end } }
    $pwdResp = Invoke-Graph -Method POST -Url ("https://graph.microsoft.com/v1.0/applications/{0}/addPassword" -f $graphAppId) -Body $pwdBody
    if ($pwdResp -and $pwdResp.secretText) {
        $clientSecret = $pwdResp.secretText
    } else {
        Write-Error "Failed to create client secret via Microsoft Graph"
        exit 1
    }
}

if (-not $clientSecret) {
    Write-Error "Failed to create client secret"
    exit 1
}

# Generate secure cookie secret (32 characters for AES-256)
Write-Host "Generating secure cookie secret..." -ForegroundColor Yellow
$cookieSecret = -join ((1..32) | ForEach-Object { '{0:x}' -f (Get-Random -Maximum 16) })

# Create Kubernetes namespace if it doesn't exist
Write-Host "Ensuring namespace '$Namespace' exists..." -ForegroundColor Yellow
kubectl create namespace $Namespace --dry-run=client -o yaml | kubectl apply -f -

# Create OAuth2 secrets (idempotent)
Write-Host "Creating Kubernetes secrets for OAuth2 proxy..." -ForegroundColor Yellow
kubectl -n $Namespace create secret generic oauth2-secrets `
    --from-literal=client-id=$appId `
    --from-literal=client-secret=$clientSecret `
    --from-literal=cookie-secret=$cookieSecret `
    --dry-run=client -o yaml | kubectl apply -f -

if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ OAuth2 secrets created successfully!" -ForegroundColor Green
} else {
    Write-Error "Failed to create OAuth2 secrets"
    exit 1
}

 # NOTE: Deployment file creation is now handled by process-template.ps1 using
 # the unified template (respondr-k8s-unified-template.yaml). We retain only
 # secret creation and app registration here for clarity.
Write-Host "Skipping legacy per-script deployment file generation (handled later by unified template)" -ForegroundColor Yellow

# Get ACR details
$acrName = az acr list -g $ResourceGroupName --query "[0].name" -o tsv
if ($acrName) {
    $acrLoginServer = az acr show --name $acrName --query loginServer -o tsv
    $imageUri = "$acrLoginServer/respondr:latest"
} else {
    Write-Warning "ACR not found, using placeholder image"
    $imageUri = "respondr:latest"
}

# Get workload identity details
$aksClusterName = az aks list --resource-group $ResourceGroupName --query "[0].name" -o tsv
if ($aksClusterName) {
    $identityClientId = az aks show --resource-group $ResourceGroupName --name $aksClusterName --query "identityProfile.kubeletidentity.clientId" -o tsv
} else {
    $identityClientId = "CLIENT_ID_PLACEHOLDER"
}

Write-Host "✅ OAuth2 Proxy setup (app registration + secrets) completed successfully!" -ForegroundColor Green
Write-Host ""
Write-Host "Configuration Summary:" -ForegroundColor Yellow
Write-Host "  App Registration: $AppName ($appId)" -ForegroundColor Cyan
Write-Host "  Sign-in audience: AzureADMultipleOrgs (multi-tenant)" -ForegroundColor Cyan
Write-Host "  Redirect URI: $redirectUri" -ForegroundColor Cyan
Write-Host "  Hostname: $hostname" -ForegroundColor Cyan
Write-Host "  Image: $imageUri" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next Steps:" -ForegroundColor Yellow
Write-Host "1. Continue with unified deployment generation (handled by deploy-complete/process-template)" -ForegroundColor White
Write-Host ""
Write-Host "2. Update your DNS to point to the Application Gateway IP" -ForegroundColor White
Write-Host ""
Write-Host "3. Test authentication by visiting: https://$hostname" -ForegroundColor White
Write-Host "   You should be redirected to Microsoft sign-in" -ForegroundColor Cyan
Write-Host ""
Write-Host "Authentication Flow:" -ForegroundColor Yellow
Write-Host "  User → Application Gateway → oauth2-proxy (port 4180) → Your App (port 8000)" -ForegroundColor Cyan
Write-Host "  - oauth2-proxy handles all Azure AD authentication" -ForegroundColor Cyan
Write-Host "  - Your application receives authenticated requests with user headers" -ForegroundColor Cyan
Write-Host "  - No changes needed to your existing FastAPI application!" -ForegroundColor Cyan
