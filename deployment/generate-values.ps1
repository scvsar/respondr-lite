param(
    [Parameter(Mandatory = $true)]
    [string]$ResourceGroupName,
    
    [Parameter(Mandatory = $true)]
    [string]$Domain,
    
    [string]$Namespace = "respondr",

    [Parameter(Mandatory = $false)]
    [string]$AppName = "respondr",

    [Parameter(Mandatory = $false)]
    [string]$HostPrefix = "respondr",

    [Parameter(Mandatory = $false)]
    [string]$ImageTag = "latest",

    # Optional overrides
    [string[]]$AllowedEmailDomains,
    [string[]]$AllowedAdminUsers
)

Write-Host "🔧 Generating deployment configuration from current Azure environment..." -ForegroundColor Cyan
Write-Host "Resource Group: $ResourceGroupName" -ForegroundColor Yellow
Write-Host "Domain: $Domain" -ForegroundColor Yellow

# Get current Azure context
Write-Host "📋 Getting Azure environment details..." -ForegroundColor Green
$azureContext = az account show --query "{subscriptionId: id, tenantId: tenantId}" -o json | ConvertFrom-Json
$azureSubscriptionId = $azureContext.subscriptionId
$azureTenantId = $azureContext.tenantId

Write-Host "   Subscription: $azureSubscriptionId" -ForegroundColor White
Write-Host "   Tenant: $azureTenantId" -ForegroundColor White

# Get ACR details
Write-Host "📦 Getting Container Registry details..." -ForegroundColor Green
$acrName = az acr list -g $ResourceGroupName --query "[0].name" -o tsv
$acrLoginServer = az acr show --name $acrName --query loginServer -o tsv
Write-Host "   ACR: $acrName" -ForegroundColor White
Write-Host "   Login Server: $acrLoginServer" -ForegroundColor White

# Get Azure OpenAI details (best-effort; continue on failure)
Write-Host "🤖 Getting Azure OpenAI details..." -ForegroundColor Green
$azureOpenAIEndpoint = ""
$azureOpenAIDeployment = ""
try {
    # List Cognitive Services accounts of kind OpenAI in the RG
    $accountsJson = az cognitiveservices account list -g $ResourceGroupName --query "[?kind=='OpenAI']" -o json 2>$null
    if ($accountsJson) {
        $accounts = $accountsJson | ConvertFrom-Json
        if ($accounts -and @($accounts).Count -gt 0) {
            # Prefer a name that matches "<rg>-openai-account"; else take first
            $expected = "$ResourceGroupName-openai-account"
            $chosen = ($accounts | Where-Object { $_.name -ieq $expected } | Select-Object -First 1)
            if (-not $chosen) { $chosen = $accounts[0] }
            $openAIName = $chosen.name

            # Endpoint
            $endpointTsv = az cognitiveservices account show -g $ResourceGroupName -n $openAIName --query "properties.endpoint" -o tsv 2>$null
            if ($endpointTsv) { $azureOpenAIEndpoint = $endpointTsv.Trim() }

            # Deployments with model names
            $deploymentsJson = az cognitiveservices account deployment list -g $ResourceGroupName -n $openAIName --query "[].{name:name, model:properties.model.name}" -o json 2>$null
            if ($deploymentsJson) {
                $deps = $deploymentsJson | ConvertFrom-Json
                if ($deps -and -not ($deps -is [array])) { $deps = @($deps) }
                if ($deps -and @($deps).Count -gt 0) {
                    $preferred = @("gpt-5-nano","gpt-4o-mini","gpt-4o","gpt-4","gpt-35-turbo")
                    $pick = $null
                    foreach ($p in $preferred) {
                        $pick = $deps | Where-Object { ($_.model -and ($_.model -ieq $p -or $_.model -ilike "$p*")) -or ($_.name -ieq $p -or $_.name -ilike "$p*") } | Select-Object -First 1
                        if ($pick) { break }
                    }
                    if (-not $pick) { $pick = $deps[0] }
                    if ($pick) { $azureOpenAIDeployment = $pick.name }
                }
            }
        } else {
            Write-Host "   No Azure OpenAI accounts found in RG $ResourceGroupName" -ForegroundColor Yellow
        }
    } else {
        Write-Host "   Unable to query Azure OpenAI accounts (no output)" -ForegroundColor Yellow
    }
} catch {
    Write-Host "   Skipping Azure OpenAI discovery due to error: $($_.Exception.Message)" -ForegroundColor Yellow
}
Write-Host "   Endpoint: $azureOpenAIEndpoint" -ForegroundColor White
Write-Host "   Deployment: $azureOpenAIDeployment" -ForegroundColor White

# Get OAuth2 app details if they exist (best-effort; don't fail generation)
Write-Host "🔐 Getting OAuth2 configuration..." -ForegroundColor Green
$oauth2ClientId = ""
try {
    $oauth2AppsRaw = az ad app list --display-name "respondr-oauth2" --query "[].{appId:appId}" -o json 2>$null
    if ($oauth2AppsRaw) {
        $oauth2Apps = $oauth2AppsRaw | ConvertFrom-Json
        if ($oauth2Apps -and $oauth2Apps.Length -gt 0) {
            $oauth2ClientId = $oauth2Apps[0].appId
            Write-Host "   OAuth2 Client ID: $oauth2ClientId" -ForegroundColor White
        } else {
            Write-Host "   OAuth2 app not found - will be created during OAuth2 setup" -ForegroundColor Yellow
        }
    } else {
        Write-Host "   Unable to query OAuth2 app (no output) - continuing" -ForegroundColor Yellow
    }
} catch {
    Write-Host "   Skipping OAuth2 app lookup due to error: $($_.Exception.Message)" -ForegroundColor Yellow
}

# Construct full hostname
if (-not $HostPrefix -or $HostPrefix -eq "") { $HostPrefix = "respondr" }
$hostname = "$HostPrefix.$Domain"
$oauth2RedirectUrl = "https://$hostname/oauth2/callback"

# Generate values.yaml
Write-Host "📝 Generating values.yaml..." -ForegroundColor Green

# Prepare YAML for allowed email domains
$allowedEmailDomainsLines = if ($AllowedEmailDomains -and $AllowedEmailDomains.Count -gt 0) {
    ($AllowedEmailDomains | ForEach-Object { '    - "' + ($_ -replace '"', '""') + '"' }) -join "`n"
} else {
    '    - "scvsar.org"' + "`n" + '    - "rtreit.com"'
}

# Prepare YAML for allowed admin users (commented examples if none provided)
$allowedAdminUsersBlock = if ($AllowedAdminUsers -and $AllowedAdminUsers.Count -gt 0) {
    ($AllowedAdminUsers | ForEach-Object { '    - "' + ($_ -replace '"', '""') + '"' }) -join "`n"
} else {
    '    # - "alice@example.com"' + "`n" + '    # - "bob@contoso.com"'
}
$valuesContent = @"
# Environment Configuration Values
# Generated on: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
# From Azure environment: $azureTenantId

# Azure Environment
azureSubscriptionId: "$azureSubscriptionId"
azureTenantId: "$azureTenantId"
resourceGroupName: "$ResourceGroupName"

# Container Registry
acrName: "$acrName"
acrLoginServer: "$acrLoginServer"
imageName: "$AppName"
imageTag: "$ImageTag"

# Azure OpenAI
azureOpenAIEndpoint: "$azureOpenAIEndpoint"
azureOpenAIDeployment: "$azureOpenAIDeployment"
# Keep in sync with create-secrets.ps1 default
azureOpenAIApiVersion: "2024-12-01-preview"

# OAuth2 Configuration
oauth2ClientId: "$oauth2ClientId"
oauth2TenantId: "$azureTenantId"
oauth2RedirectUrl: "$oauth2RedirectUrl"
multiTenantAuth: "true"
allowedEmailDomains:
$allowedEmailDomainsLines
allowedAdminUsers:
$allowedAdminUsersBlock

# Domain Configuration
domain: "$Domain"
hostname: "$hostname"

# Application Configuration
namespace: "$Namespace"
appName: "$AppName"
replicas: 2
useOAuth2: "true"
"@

$valuesContent | Out-File -FilePath "values.yaml" -Encoding UTF8

Write-Host "✅ Generated values.yaml with current environment configuration" -ForegroundColor Green
Write-Host ""
Write-Host "📋 Configuration Summary:" -ForegroundColor Cyan
Write-Host "   Full Image: $acrLoginServer/${AppName}:${ImageTag}" -ForegroundColor White
Write-Host "   Hostname: $hostname" -ForegroundColor White
Write-Host "   OAuth2 Redirect: $oauth2RedirectUrl" -ForegroundColor White
Write-Host "   Tenant ID: $azureTenantId" -ForegroundColor White
Write-Host "   App Name: $AppName" -ForegroundColor White
Write-Host ""
Write-Host "⚠️  IMPORTANT: This values.yaml file contains environment-specific configuration" -ForegroundColor Yellow
Write-Host "   and should NEVER be committed to git. It's in .gitignore for this reason." -ForegroundColor Yellow
