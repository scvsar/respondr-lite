param(
    [Parameter(Mandatory=$true)]
    [string]$ResourceGroupName,

    [Parameter(Mandatory=$false)]
    [string]$Domain = "rtreit.com",

    [Parameter(Mandatory=$false)]
    [string]$Namespace = "respondr",

    [ValidateSet('preflight','env','app','all')]
    [string]$Phase = 'all',

    [Parameter(Mandatory=$false)]
    [switch]$Strict
)

Write-Host "Respondr Validation" -ForegroundColor Green
Write-Host "====================" -ForegroundColor Green
Write-Host "Resource Group: $ResourceGroupName" -ForegroundColor Cyan
Write-Host "Domain: $Domain" -ForegroundColor Cyan
Write-Host "Namespace: $Namespace" -ForegroundColor Cyan

function Invoke-Preflight {
    Write-Host "\n[Phase] Preflight (Azure prerequisites)" -ForegroundColor Yellow
    & (Join-Path $PSScriptRoot 'pre-deploy-check.ps1') -ResourceGroupName $ResourceGroupName
    if ($LASTEXITCODE -ne 0) { throw "Preflight checks failed" }
}

function Invoke-EnvValidation {
    Write-Host "\n[Phase] Environment validation (AKS/AGIC/ACR/cert-manager)" -ForegroundColor Yellow

    # kubectl connectivity
    try {
        kubectl cluster-info --request-timeout=5s | Out-Null
        Write-Host "✓ kubectl connected to cluster" -ForegroundColor Green
    } catch { throw "kubectl cannot reach the cluster" }

    # Namespace present or creatable (dry-run)
    kubectl create namespace $Namespace --dry-run=client -o yaml 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { Write-Host "✓ Namespace validated: $Namespace" -ForegroundColor Green }
    else { throw "Namespace validation failed: $Namespace" }

    # AGIC enabled and AppGW detectable
    $deploy = az deployment group show --resource-group $ResourceGroupName --name main -o json 2>$null | ConvertFrom-Json
    $aksName = $deploy.properties.outputs.aksClusterName.value
    $location = $deploy.properties.outputs.location.value
    $agicId = az aks show --resource-group $ResourceGroupName --name $aksName --query "addonProfiles.ingressApplicationGateway.config.effectiveApplicationGatewayId" -o tsv 2>$null
    if (-not $agicId) { throw "AGIC not enabled or Application Gateway ID not found" }
    # Query the App Gateway directly by resource ID to avoid guessing its resource group
    $portsJson = az network application-gateway show --ids $agicId --query "frontendPorts" -o json 2>$null
    if ($portsJson) {
        $ports = $portsJson | ConvertFrom-Json
        if ($ports | Where-Object { $_.port -eq 443 }) { Write-Host "✓ AppGW frontend port 443 present" -ForegroundColor Green }
        else { Write-Host "⚠️ AppGW 443 not found yet (will be added during deploy)" -ForegroundColor Yellow }
    } else { Write-Host "⚠️ Could not list AppGW ports (AGIC may still be initializing)" -ForegroundColor Yellow }

    # cert-manager CRDs and issuer
    $crdPresent = $false
    try {
        kubectl get crd certificates.cert-manager.io 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { $crdPresent = $true }
    } catch { $crdPresent = $false }

    if ($crdPresent) {
        Write-Host "✓ cert-manager CRDs present" -ForegroundColor Green
    } else {
        if ($Strict) { throw "cert-manager CRDs not found" }
        else { Write-Host "ℹ️ cert-manager CRDs not found (post-deploy installs cert-manager)" -ForegroundColor Cyan }
    }

    $issuer = kubectl get clusterissuer letsencrypt-prod -o name 2>$null
    if ($issuer) { Write-Host "✓ ClusterIssuer letsencrypt-prod present" -ForegroundColor Green }
    else { Write-Host "ℹ️ ClusterIssuer not found yet (post-deploy should create)" -ForegroundColor Cyan }

    # ACR access sanity (discover ACR and list repos)
    $acrName = az acr list -g $ResourceGroupName --query "[0].name" -o tsv 2>$null
    if ($acrName) {
        az acr repository list --name $acrName -o tsv 2>$null | Out-Null
        Write-Host "✓ ACR reachable: $acrName" -ForegroundColor Green
    } else { Write-Host "ℹ️ No ACR found yet (will be created by infra)" -ForegroundColor Cyan }

    # OAuth2 secrets presence (if using OAuth2)
    $oauthSecret = kubectl get secret oauth2-secrets -n $Namespace -o name 2>$null
    if ($oauthSecret) { Write-Host "✓ oauth2-secrets present" -ForegroundColor Green } else { Write-Host "ℹ️ oauth2-secrets not found (setup-oauth2.ps1 will create)" -ForegroundColor Cyan }

    # Template generation dry-run: ensure values and placeholders
    if (Test-Path (Join-Path $PSScriptRoot 'values.yaml')) {
        $content = Get-Content (Join-Path $PSScriptRoot 'respondr-k8s-unified-template.yaml') -Raw
        $values = Get-Content (Join-Path $PSScriptRoot 'values.yaml') -Raw
        if (-not $values) { throw "values.yaml exists but is empty" }
        # Quick placeholder sanity
        if ($content -notmatch '{{ACR_IMAGE_PLACEHOLDER}}') { Write-Host "✓ Template placeholders look updated" -ForegroundColor Green }
        Write-Host "✓ values.yaml present" -ForegroundColor Green
    } else { Write-Host "ℹ️ values.yaml not present (generate-values.ps1 will create)" -ForegroundColor Cyan }
}

function Invoke-AppValidation {
    Write-Host "\n[Phase] App validation (post-deploy smoke)" -ForegroundColor Yellow
    # Deployment readiness
    $dep = kubectl get deploy respondr-deployment -n $Namespace -o json 2>$null | ConvertFrom-Json
    if ($dep) {
        $available = ($dep.status.availableReplicas -ge 1)
        if ($available) { Write-Host "✓ Deployment has available replicas" -ForegroundColor Green }
        else { Write-Host "⚠️ Deployment not yet available" -ForegroundColor Yellow }
    } else { Write-Host "ℹ️ Deployment not found yet" -ForegroundColor Cyan }

    # Ingress IP
    $ingressIp = kubectl get ingress respondr-ingress -n $Namespace -o jsonpath="{.status.loadBalancer.ingress[0].ip}" 2>$null
    if ($ingressIp) { Write-Host "✓ Ingress IP: $ingressIp" -ForegroundColor Green } else { Write-Host "ℹ️ Ingress IP not assigned yet" -ForegroundColor Cyan }

    # Cert status
    $cert = kubectl get certificate respondr-tls-letsencrypt -n $Namespace -o json 2>$null | ConvertFrom-Json
    if ($cert) {
        $cond = ($cert.status.conditions | Where-Object { $_.type -eq 'Ready' })
        if ($cond -and $cond.status -eq 'True') { Write-Host "✓ TLS certificate Ready" -ForegroundColor Green }
        else { Write-Host "ℹ️ TLS certificate not ready yet" -ForegroundColor Cyan }
    }
}

switch ($Phase) {
    'preflight' { Invoke-Preflight }
    'env' { Invoke-EnvValidation }
    'app' { Invoke-AppValidation }
    'all' {
        try { Invoke-Preflight } catch { Write-Host $_ -ForegroundColor Red; exit 1 }
        try { Invoke-EnvValidation } catch { Write-Host $_ -ForegroundColor Red; exit 1 }
        try { Invoke-AppValidation } catch { Write-Host $_ -ForegroundColor Yellow }
    }
}

Write-Host "\nValidation completed." -ForegroundColor Green
