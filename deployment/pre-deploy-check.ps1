<#
.SYNOPSIS
    Pre-deployment validation script for respondr app.

.DESCRIPTION
    Validates prerequisites and configuration before deploying the respondr application.
    - Checks Azure CLI login and subscription
    - Validates resource group
    - Checks for required Azure resource providers
    - Validates network configuration
#>

param (
    [Parameter(Mandatory)][string]$ResourceGroupName,
    [Parameter()][string]$Location = "westus"
)

Write-Host "Starting pre-deployment validation..." -ForegroundColor Green

# 1) Check Azure CLI login
Write-Host "`nChecking Azure CLI authentication..." -ForegroundColor Yellow
$account = az account show 2>$null | ConvertFrom-Json
if (-not $account) {
    Write-Host "Error: Not logged in to Azure CLI. Run 'az login' first." -ForegroundColor Red
    exit 1
}
Write-Host "  Logged in as: $($account.user.name)" -ForegroundColor Green
Write-Host "  Subscription: $($account.name) ($($account.id))" -ForegroundColor Green

# 2) Check resource group
Write-Host "`nChecking resource group..." -ForegroundColor Yellow
$rg = az group show --name $ResourceGroupName 2>$null | ConvertFrom-Json
if (-not $rg) {
    Write-Host "Error: Resource group '$ResourceGroupName' not found." -ForegroundColor Red
    exit 1
}
Write-Host "  Resource group: $($rg.name) in $($rg.location)" -ForegroundColor Green

# 3) Check required resource providers
Write-Host "`nChecking Azure resource providers..." -ForegroundColor Yellow
$requiredProviders = @(
    "Microsoft.ContainerService",
    "Microsoft.ContainerRegistry", 
    "Microsoft.CognitiveServices",
    "Microsoft.Storage",
    "Microsoft.Network",
    "Microsoft.ManagedIdentity"
)

$providersOk = $true
foreach ($provider in $requiredProviders) {
    $providerState = az provider show --namespace $provider --query "registrationState" -o tsv 2>$null
    if ($providerState -eq "Registered") {
        Write-Host "  ✓ $provider" -ForegroundColor Green
    } else {
        Write-Host "  ✗ $provider (state: $providerState)" -ForegroundColor Red
        Write-Host "    Run: az provider register --namespace $provider" -ForegroundColor Yellow
        $providersOk = $false
    }
}

if (-not $providersOk) {
    Write-Host "`nError: Some required resource providers are not registered." -ForegroundColor Red
    exit 1
}

# 4) Check Azure CLI extensions
Write-Host "`nChecking Azure CLI extensions..." -ForegroundColor Yellow
$extensions = az extension list --query "[].name" -o tsv 2>$null

# Check for conflicting extensions that should be removed
$conflictingExtensions = @("aks-preview")
foreach ($conflictExt in $conflictingExtensions) {
    if ($extensions -contains $conflictExt) {
        Write-Host "  ⚠️  Conflicting extension '$conflictExt' found. This should be removed to avoid import errors." -ForegroundColor Yellow
        Write-Host "    Run: az extension remove --name $conflictExt" -ForegroundColor Yellow
    } else {
        Write-Host "  ✓ No conflicting extensions found" -ForegroundColor Green
    }
}

# Check for recommended extensions
if ($extensions -contains "application-gateway-preview") {
    Write-Host "  ✓ application-gateway-preview extension installed" -ForegroundColor Green
} else {
    Write-Host "  ℹ️  application-gateway-preview extension not found (will be installed during post-deploy)" -ForegroundColor Cyan
}

# 5) Check quota limits (basic check)
Write-Host "`nChecking Azure quotas..." -ForegroundColor Yellow
$quotaUsage = az vm list-usage --location $Location --query "[?name.value=='cores'].{Current:currentValue, Limit:limit}" -o json | ConvertFrom-Json
if ($quotaUsage.Count -gt 0) {
    $coreUsage = $quotaUsage[0]
    $availableCores = $coreUsage.Limit - $coreUsage.Current
    Write-Host "  CPU cores: $($coreUsage.Current)/$($coreUsage.Limit) used, $availableCores available" -ForegroundColor Cyan
    if ($availableCores -lt 8) {
        Write-Host "  Warning: Low CPU core availability. AKS needs at least 4-8 cores." -ForegroundColor Yellow
    }
}

# 6) Check kubectl installation
Write-Host "`nChecking kubectl..." -ForegroundColor Yellow
if (Get-Command kubectl -ErrorAction SilentlyContinue) {
    $kubectlVersion = kubectl version --client --short 2>$null
    Write-Host "  ✓ kubectl installed: $kubectlVersion" -ForegroundColor Green
} else {
    Write-Host "  ! kubectl not found. Install kubectl for AKS management." -ForegroundColor Yellow
}

# 7) Validate network configuration
Write-Host "`nValidating network configuration..." -ForegroundColor Yellow
$vnetExists = az network vnet show --name "respondr-vnet" --resource-group $ResourceGroupName 2>$null
if ($vnetExists) {
    Write-Host "  ✓ VNet 'respondr-vnet' already exists" -ForegroundColor Green
    
    # Check subnets
    $aksSubnet = az network vnet subnet show --name "aks-subnet" --vnet-name "respondr-vnet" --resource-group $ResourceGroupName 2>$null
    $appGwSubnet = az network vnet subnet show --name "appgw-subnet" --vnet-name "respondr-vnet" --resource-group $ResourceGroupName 2>$null
    
    if ($aksSubnet) { Write-Host "  ✓ AKS subnet exists" -ForegroundColor Green }
    else { Write-Host "  ! AKS subnet missing" -ForegroundColor Yellow }
    
    if ($appGwSubnet) { Write-Host "  ✓ Application Gateway subnet exists" -ForegroundColor Green }
    else { Write-Host "  ! Application Gateway subnet missing" -ForegroundColor Yellow }
} else {
    Write-Host "  ✓ VNet will be created during deployment" -ForegroundColor Green
}

# 8) Check for existing AKS clusters with similar names
Write-Host "`nChecking for existing AKS clusters..." -ForegroundColor Yellow
try {
    $existingClusters = az aks list --resource-group $ResourceGroupName --query "[].name" -o tsv 2>$null
    if ($LASTEXITCODE -eq 0 -and $existingClusters) {
        Write-Host "  Existing clusters in resource group: $($existingClusters -join ', ')" -ForegroundColor Cyan
        if ($existingClusters -contains "respondr-aks-cluster-v2") {
            Write-Host "  Warning: Target cluster 'respondr-aks-cluster-v2' already exists" -ForegroundColor Yellow
        }
    } else {
        Write-Host "  ✓ No existing AKS clusters found" -ForegroundColor Green
    }
} catch {
    Write-Host "  ✓ AKS cluster check completed (no conflicts detected)" -ForegroundColor Green
}

Write-Host "`nPre-deployment validation completed!" -ForegroundColor Green
Write-Host "`nNext steps:" -ForegroundColor Cyan
Write-Host "  1. Run: .\deployment\main.bicep deployment" -ForegroundColor White
Write-Host "  2. Run: .\deployment\post-deploy.ps1 -ResourceGroupName $ResourceGroupName" -ForegroundColor White
Write-Host "  3. Run: .\deployment\deploy-to-k8s.ps1" -ForegroundColor White
