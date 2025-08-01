<#
.SYNOPSIS
    Post-deployment configuration for the response-tracking-render app.

.DESCRIPTION
    - Fetches deployment outputs (AKS cluster name, ACR name, OpenAI account name)
    - Gets AKS credentials
    - Attaches ACR to AKS (if present)
    - Imports a test image into ACR
    - Deploys a test pod in AKS to verify ACR integration
    - Checks the provisioning state of OpenAI & Storage accounts
#>

param (
    [Parameter(Mandatory)][string]$ResourceGroupName,
    [Parameter()][string]$Location = "westus"
)

Write-Host "Starting post-deployment configuration..." -ForegroundColor Green

# 1) Retrieve deployment outputs
Write-Host "Retrieving deployment outputs..." -ForegroundColor Yellow
$deploy = az deployment group show `
    --resource-group $ResourceGroupName `
    --name main -o json | ConvertFrom-Json

# Assumes your Bicep defines outputs: aksClusterName, acrName, openAiAccountName
$aksClusterName     = $deploy.properties.outputs.aksClusterName.value
$acrName            = $deploy.properties.outputs.acrName.value
$openAiAccountName  = $deploy.properties.outputs.openAiAccountName.value

if (-not $aksClusterName)    { throw "❌ Missing aksClusterName output!" }
if (-not $openAiAccountName) { throw "❌ Missing openAiAccountName output!" }

# 2) Get Storage account name dynamically (if you didn’t output it)
$storageAccountName = az storage account list `
    --resource-group $ResourceGroupName `
    --query "[0].name" -o tsv

Write-Host "  AKS Cluster:  $aksClusterName"
Write-Host "  ACR:          $($acrName  -or '<none found>')"
Write-Host "  OpenAIAcct:   $openAiAccountName"
Write-Host "  StorageAcct:  $storageAccountName"

# 3) AKS credentials
Write-Host "`nGetting AKS credentials..." -ForegroundColor Yellow
az aks get-credentials `
    --resource-group $ResourceGroupName `
    --name $aksClusterName `
    --overwrite-existing

# 4) Attach ACR (if one exists)
if ($acrName) {
    Write-Host "`nAttaching ACR '$acrName' to AKS cluster..." -ForegroundColor Yellow
    az aks update `
        --name $aksClusterName `
        --resource-group $ResourceGroupName `
        --attach-acr $acrName
} else {
    Write-Host "`nℹ️  No ACR name found—skipping attach step." -ForegroundColor Cyan
}

# 5) Import test image into ACR
if ($acrName) {
    Write-Host "`nImporting test image to ACR..." -ForegroundColor Yellow
    $importResult = az acr import `
        --name $acrName `
        --source docker.io/library/nginx:latest `
        --image nginx:test 2>&1

    if ($LASTEXITCODE -ne 0) {
        if ($importResult -match 'already exists') {
            Write-Host "✔ nginx:test already exists in ACR." -ForegroundColor Green
        } else {
            Write-Host "⚠️  Import failed: $importResult" -ForegroundColor Yellow
        }
    } else {
        Write-Host "✔ Successfully imported nginx:test" -ForegroundColor Green
    }
}

# 6) Deploy and validate a test pod
Write-Host "`nDeploying test pod to verify AKS & ACR integration..." -ForegroundColor Yellow
$testPodYaml = Join-Path $PSScriptRoot "test-pod.yaml"

if (Test-Path $testPodYaml) {
    if (Get-Command kubectl -ErrorAction SilentlyContinue) {
        kubectl apply -f $testPodYaml
        Write-Host "Waiting for nginx-test pod to be ready..." -ForegroundColor Yellow
        kubectl wait --for=condition=Ready pod/nginx-test --timeout=120s
        Write-Host "✔ Test pod is running." -ForegroundColor Green
    } else {
        Write-Host "⚠️  kubectl not installed—skip pod deployment." -ForegroundColor Yellow
        Write-Host "   To test manually, install kubectl and run:" -ForegroundColor Cyan
        Write-Host "     kubectl apply -f $testPodYaml"
    }
} else {
    Write-Host "⚠️  test-pod.yaml not found at $testPodYaml" -ForegroundColor Red
}

# 7) Check OpenAI account provisioning state
Write-Host "`nChecking OpenAI account status..." -ForegroundColor Yellow
$openAiState = az cognitiveservices account show `
    --name $openAiAccountName `
    --resource-group $ResourceGroupName `
    --query "properties.provisioningState" -o tsv
Write-Host "✔ OpenAI provisioningState: $openAiState" -ForegroundColor Cyan

# 8) Check Storage account provisioning state
if ($storageAccountName) {
    Write-Host "`nChecking Storage account status..." -ForegroundColor Yellow
    $storageState = az storage account show `
        --name $storageAccountName `
        --resource-group $ResourceGroupName `
        --query "provisioningState" -o tsv
    Write-Host "✔ Storage provisioningState: $storageState" -ForegroundColor Cyan
}

Write-Host "`n🎉 Post-deployment configuration completed successfully!" -ForegroundColor Green
