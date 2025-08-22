#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Upgrade/Redeploy Respondr application to Kubernetes with new container image

.DESCRIPTION
    This script handles the complete upgrade workflow:
    1. Builds a new container image with version tag
    2. Pushes to Azure Container Registry
    3. Updates Kubernetes deployment with new image
    4. Waits for rollout completion
    5. Verifies deployment health

.PARAMETER Version
    Version tag for the new container image (e.g., "v1.1", "v2.0")

.PARAMETER ResourceGroupName
    Azure resource group name containing the ACR

.PARAMETER Namespace
    Kubernetes namespace (default: "default")

.PARAMETER SkipBuild
    Skip building new container image (use existing image with specified version)

.PARAMETER RollbackOnFailure
    Automatically rollback if deployment fails

.EXAMPLE
    .\upgrade-k8s.ps1 -Version "v1.1" -ResourceGroupName "respondr"

.EXAMPLE
    .\upgrade-k8s.ps1 -Version "v1.2" -ResourceGroupName "respondr" -SkipBuild -RollbackOnFailure
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$Version,
    
    [Parameter(Mandatory=$true)]
    [string]$ResourceGroupName,
    
    [Parameter(Mandatory=$false)]
    [string]$Namespace = "respondr",
    
    [Parameter(Mandatory=$false)]
    [switch]$SkipBuild = $false,
    
    [Parameter(Mandatory=$false)]
    [switch]$RollbackOnFailure = $false,
    
    [Parameter(Mandatory=$false)]
    [switch]$DryRun = $false
)

# Script variables
$ErrorActionPreference = "Stop"
$deploymentName = "respondr-deployment"
try {
    if (Test-Path (Join-Path $PSScriptRoot 'values.yaml')) {
        $vals = Get-Content (Join-Path $PSScriptRoot 'values.yaml') -Raw
        $m = ($vals | Select-String 'appName: "([^"]+)"').Matches
        if ($m.Count -gt 0) { $deploymentName = "$($m[0].Groups[1].Value)-deployment" }
    }
} catch {}
$containerName = "respondr"

Write-Host "Respondr Kubernetes Upgrade Script" -ForegroundColor Green
Write-Host "==================================" -ForegroundColor Green
Write-Host "Version: $Version" -ForegroundColor Cyan
Write-Host "Resource Group: $ResourceGroupName" -ForegroundColor Cyan
Write-Host "Namespace: $Namespace" -ForegroundColor Cyan

# Function to check prerequisites
function Test-Prerequisites {
    Write-Host "Checking prerequisites..." -ForegroundColor Yellow
    
    # Check kubectl
    if (-not (Get-Command kubectl -ErrorAction SilentlyContinue)) {
        throw "kubectl is not installed or not in PATH"
    }
    
    # Check Docker (only if not skipping build)
    if (-not $SkipBuild -and -not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker is not installed or not in PATH"
    }
    
    # Check Azure CLI
    if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
        throw "Azure CLI is not installed or not in PATH"
    }
    
    # Check cluster connection
    try {
        kubectl cluster-info --request-timeout=5s | Out-Null
        Write-Host "Connected to Kubernetes cluster" -ForegroundColor Green
    } catch {
        throw "Cannot connect to Kubernetes cluster. Please check your kubeconfig."
    }
    
    # Check if deployment exists
    $deploymentExists = kubectl get deployment $deploymentName -n $Namespace 2>$null
    if (-not $deploymentExists) {
        throw "Deployment '$deploymentName' not found in namespace '$Namespace'. Run initial deployment first."
    }
    
    Write-Host "Prerequisites check passed" -ForegroundColor Green
}

# Function to get ACR details
function Get-AcrDetails {
    Write-Host "Getting Azure Container Registry details..." -ForegroundColor Yellow
    
    $acrName = az acr list -g $ResourceGroupName --query "[0].name" -o tsv
    if (-not $acrName) {
        throw "No Azure Container Registry found in resource group '$ResourceGroupName'"
    }
    
    $acrLoginServer = az acr show --name $acrName --query loginServer -o tsv
    
    Write-Host "ACR Name: $acrName" -ForegroundColor Cyan
    Write-Host "ACR Login Server: $acrLoginServer" -ForegroundColor Cyan
    
    return @{
        Name = $acrName
        LoginServer = $acrLoginServer
    }
}

# Function to build and push new image
function Build-AndPushImage {
    param($AcrDetails)
    
    Write-Host "Building new container image..." -ForegroundColor Yellow
    # Navigate to project root
    $projectRoot = Split-Path $PSScriptRoot -Parent
    Push-Location $projectRoot
    
    try {
        # Login to ACR
        Write-Host "Logging into ACR..." -ForegroundColor Yellow
        az acr login --name $AcrDetails.Name | Out-Null
        
        # Build image with version tag
        $fullImageName = "$($AcrDetails.LoginServer)/respondr:$Version"
        $latestImageName = "$($AcrDetails.LoginServer)/respondr:latest"
        
        Write-Host "Building image: $fullImageName" -ForegroundColor Cyan
        if ($DryRun) {
            Write-Host "DRY RUN: Would build docker image" -ForegroundColor Yellow
        } else {
            # Build with clean output - suppress progress
            docker build -t $fullImageName -t $latestImageName . --quiet | Out-Null
            if ($LASTEXITCODE -ne 0) {
                # If quiet fails, try without quiet but capture output properly
                Write-Host "Quiet build failed, retrying with full output..." -ForegroundColor Yellow
                docker build -t $fullImageName -t $latestImageName . | Out-Null
                if ($LASTEXITCODE -ne 0) {
                    throw "Docker build failed"
                }
            }
        }
        
        # Push to ACR
        Write-Host "Pushing image to ACR..." -ForegroundColor Yellow
        if ($DryRun) {
            Write-Host "DRY RUN: Would push images to ACR" -ForegroundColor Yellow
        } else {
            # Push the versioned image
            docker push $fullImageName | Out-Null
            if ($LASTEXITCODE -ne 0) {
                throw "Docker push failed for versioned image"
            }
            
            # Push the latest image
            docker push $latestImageName | Out-Null
            if ($LASTEXITCODE -ne 0) {
                throw "Docker push failed for latest image"
            }
        }
        
        Write-Host "Image build and push completed successfully" -ForegroundColor Green
        return $fullImageName
        
    } finally {
        Pop-Location
    }
}

# Function to update Kubernetes deployment
function Update-KubernetesDeployment {
    param($ImageName, $AcrDetails)
    
    Write-Host "Updating Kubernetes deployment..." -ForegroundColor Yellow
    
    # Get current image for potential rollback
    $currentImage = kubectl get deployment $deploymentName -n $Namespace -o jsonpath='{.spec.template.spec.containers[0].image}' 2>$null
    if ($currentImage) {
        Write-Host "Current image: $currentImage" -ForegroundColor Cyan
    }
    Write-Host "New image: $ImageName" -ForegroundColor Cyan
      # Update deployment image
    if ($DryRun) {
        Write-Host "DRY RUN: Would update deployment image" -ForegroundColor Yellow
    } else {
        kubectl set image "deployment/$deploymentName" "$containerName=$ImageName" -n $Namespace
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to update deployment image"
        }
    }
    
    # Wait for rollout
    Write-Host "Waiting for deployment rollout..." -ForegroundColor Yellow
    if ($DryRun) {
        Write-Host "DRY RUN: Would wait for rollout completion" -ForegroundColor Yellow
    } else {
        kubectl rollout status deployment/$deploymentName -n $Namespace --timeout=300s
        if ($LASTEXITCODE -ne 0) {
            if ($RollbackOnFailure) {
                Write-Host "Deployment failed, rolling back..." -ForegroundColor Red
                kubectl rollout undo deployment/$deploymentName -n $Namespace
                kubectl rollout status deployment/$deploymentName -n $Namespace --timeout=300s
                throw "Deployment failed and was rolled back to previous version"
            } else {
                throw "Deployment rollout failed"
            }
        }
    }
    
    Write-Host "Deployment updated successfully" -ForegroundColor Green
    return $currentImage
}

# Function to verify deployment health
function Test-DeploymentHealth {
    Write-Host "Verifying deployment health..." -ForegroundColor Yellow
    
    if ($DryRun) {
        Write-Host "DRY RUN: Would verify deployment health" -ForegroundColor Yellow
        return
    }
    
    # Check pod status
    $pods = kubectl get pods -l app=respondr -n $Namespace -o json | ConvertFrom-Json
    $readyPods = ($pods.items | Where-Object { $_.status.conditions | Where-Object { $_.type -eq "Ready" -and $_.status -eq "True" } }).Count
    $totalPods = $pods.items.Count
    
    Write-Host "Ready pods: $readyPods/$totalPods" -ForegroundColor Cyan
    
    if ($readyPods -eq 0) {
        # Get pod details for troubleshooting
        Write-Host "Pod details:" -ForegroundColor Yellow
        kubectl describe pods -l app=respondr -n $Namespace
        throw "No pods are ready"
    }
    
    # Test API endpoint (if ingress is configured)
    try {
        $response = Invoke-WebRequest -Uri "http://respondr.local/api/responders" -TimeoutSec 10 -ErrorAction Stop
        Write-Host "API health check passed (HTTP $($response.StatusCode))" -ForegroundColor Green
    } catch {
        Write-Host "API health check failed (this may be expected if ingress is not configured): $_" -ForegroundColor Yellow
    }
    
    Write-Host "Deployment health verification completed" -ForegroundColor Green
}

# Function to display deployment status
function Show-DeploymentStatus {
    Write-Host "Current deployment status:" -ForegroundColor Green
    
    if ($DryRun) {
        Write-Host "DRY RUN: Would show deployment status" -ForegroundColor Yellow
        return
    }
    
    Write-Host "Pods:" -ForegroundColor Cyan
    kubectl get pods -l app=respondr -n $Namespace
    
    Write-Host "`nServices:" -ForegroundColor Cyan
    kubectl get services -l app=respondr -n $Namespace
    
    Write-Host "`nDeployment:" -ForegroundColor Cyan
    kubectl get deployment $deploymentName -n $Namespace
    
    Write-Host "`nRollout history:" -ForegroundColor Cyan
    kubectl rollout history deployment/$deploymentName -n $Namespace
}

# Main execution
try {
    Test-Prerequisites
    
    $acrDetails = Get-AcrDetails
    
    if ($SkipBuild) {
        $imageName = "$($acrDetails.LoginServer)/respondr:$Version"
        Write-Host "Skipping build, using existing image: $imageName" -ForegroundColor Yellow
    } else {
        $imageName = Build-AndPushImage -AcrDetails $acrDetails
    }
    
    $previousImage = Update-KubernetesDeployment -ImageName $imageName -AcrDetails $acrDetails
    
    Test-DeploymentHealth
    
    Show-DeploymentStatus
    
    Write-Host "`nUpgrade completed successfully!" -ForegroundColor Green
    Write-Host "Previous image: $previousImage" -ForegroundColor Cyan
    Write-Host "Current image: $imageName" -ForegroundColor Cyan
    Write-Host "Version deployed: $Version" -ForegroundColor Cyan
    
    if (-not $DryRun) {
        Write-Host "`nTo rollback if needed:" -ForegroundColor Yellow
        Write-Host "kubectl rollout undo deployment/$deploymentName -n $Namespace" -ForegroundColor White
    }
    
} catch {
    Write-Host "`nUpgrade failed: $_" -ForegroundColor Red
    Write-Host "`nFor troubleshooting:" -ForegroundColor Yellow
    Write-Host "kubectl get pods -l app=respondr -n $Namespace" -ForegroundColor White
    Write-Host "kubectl logs -l app=respondr -n $Namespace" -ForegroundColor White
    Write-Host "kubectl describe deployment $deploymentName -n $Namespace" -ForegroundColor White
    exit 1
}
