# Post-deployment script for the response-tracking-render application
# This script performs necessary configuration tasks after deploying the Azure resources

param (
    [Parameter(Mandatory=$true)]
    [string]$ResourceGroupName,

    [Parameter(Mandatory=$false)]
    [string]$Location = "westus"
)

Write-Host "Starting post-deployment configuration..." -ForegroundColor Green

# Get deployment outputs
Write-Host "Retrieving resource information..." -ForegroundColor Yellow
$aksClusterName = "response-aks-cluster"
$acrName = "responseacr"
$openAiAccountName = "response-openai-account"
$storageAccountName = (az storage account list --resource-group $ResourceGroupName --query "[0].name" -o tsv)

# Get AKS credentials
Write-Host "Getting AKS credentials..." -ForegroundColor Yellow
az aks get-credentials --resource-group $ResourceGroupName --name $aksClusterName --overwrite-existing

# Attach ACR to AKS
Write-Host "Attaching ACR to AKS cluster..." -ForegroundColor Yellow
az aks update --name $aksClusterName --resource-group $ResourceGroupName --attach-acr $acrName

# Import a test image to verify ACR functionality
Write-Host "Importing test image to ACR..." -ForegroundColor Yellow
$importResult = az acr import --name $acrName --source docker.io/library/nginx:latest --image nginx:test 2>&1
if ($LASTEXITCODE -ne 0) {
    if ($importResult -like "*already exists*") {
        Write-Host "Image nginx:test already exists in ACR, continuing..." -ForegroundColor Cyan
    } else {
        Write-Host "Warning: Failed to import test image: $importResult" -ForegroundColor Yellow
    }
} else {
    Write-Host "Successfully imported nginx:test to ACR" -ForegroundColor Green
}

# Deploy a test pod to verify AKS and ACR integration
Write-Host "Deploying test pod to verify AKS and ACR integration..." -ForegroundColor Yellow
$testPodYamlPath = Join-Path $PSScriptRoot "test-pod.yaml"

# Check if kubectl is installed
$kubectlInstalled = $null -ne (Get-Command kubectl -ErrorAction SilentlyContinue)

if ($kubectlInstalled) {
    # Use kubectl directly
    kubectl apply -f $testPodYamlPath
    
    # Verify the pod is running
    Write-Host "Waiting for test pod to be ready..." -ForegroundColor Yellow
    kubectl wait --for=condition=Ready pod/nginx-test --timeout=120s
} else {
    # Use az aks command as an alternative
    Write-Host "kubectl not found, we'll skip the test pod deployment." -ForegroundColor Yellow
    Write-Host "To manually test the deployment later, install kubectl and run:" -ForegroundColor Cyan
    Write-Host "kubectl apply -f $testPodYamlPath" -ForegroundColor Cyan
}

# Check OpenAI account status
Write-Host "Checking OpenAI account status..." -ForegroundColor Yellow
$openAiStatus = az cognitiveservices account show --name $openAiAccountName --resource-group $ResourceGroupName --query "properties.provisioningState" -o tsv
Write-Host "OpenAI account status: $openAiStatus" -ForegroundColor Cyan

# Check Storage account status
Write-Host "Checking Storage account status..." -ForegroundColor Yellow
$storageStatus = az storage account show --name $storageAccountName --resource-group $ResourceGroupName --query "provisioningState" -o tsv
Write-Host "Storage account status: $storageStatus" -ForegroundColor Cyan

Write-Host "Post-deployment configuration completed successfully!" -ForegroundColor Green
Write-Host "Resources deployed:"
Write-Host "  - AKS Cluster: $aksClusterName"
Write-Host "  - Azure Container Registry: $acrName"
Write-Host "  - OpenAI Account: $openAiAccountName"
Write-Host "  - Storage Account: $storageAccountName"
