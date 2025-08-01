#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Quick redeploy script for respondr application

.DESCRIPTION
    Simple script for common redeployment scenarios:
    - Redeploy with latest code changes
    - Quick restart of existing deployment
    - Update configuration

.PARAMETER Action
    Action to perform: "build", "restart", "update-config"

.PARAMETER ResourceGroupName
    Azure resource group name (required for "build" action)

.PARAMETER Namespace
    Kubernetes namespace (default: "default")

.EXAMPLE
    .\redeploy.ps1 -Action "build" -ResourceGroupName "respondr"
    
.EXAMPLE
    .\redeploy.ps1 -Action "restart"
#>

param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("build", "restart", "update-config")]
    [string]$Action,
    
    [Parameter(Mandatory=$false)]
    [string]$ResourceGroupName,
    
    [Parameter(Mandatory=$false)]
    [string]$Namespace = "default"
)

$deploymentName = "respondr-deployment"
$containerName = "respondr"  # Container name for image updates

Write-Host "Respondr Quick Redeploy" -ForegroundColor Green
Write-Host "======================" -ForegroundColor Green
Write-Host "Action: $Action" -ForegroundColor Cyan

switch ($Action) {
    "build" {
        if (-not $ResourceGroupName) {
            Write-Error "ResourceGroupName is required for build action"
            exit 1
        }
        
        # Generate version based on current timestamp
        $version = "v$(Get-Date -Format 'yyyy.MM.dd-HHmm')"
        Write-Host "Building and deploying version: $version" -ForegroundColor Yellow
        
        try {
            # Call the main upgrade script
            & "$PSScriptRoot\upgrade-k8s.ps1" -Version $version -ResourceGroupName $ResourceGroupName -Namespace $Namespace
            
            # If the upgrade script failed, we can manually try to fix the deployment
            if ($LASTEXITCODE -ne 0) {
                Write-Host "Upgrade script reported an error. Attempting manual recovery..." -ForegroundColor Yellow
                
                # Get ACR details directly
                $acrName = az acr list -g $ResourceGroupName --query "[0].name" -o tsv
                $acrLoginServer = az acr show --name $acrName --query loginServer -o tsv
                
                # Format image name properly
                $fullImageName = "$acrLoginServer/$containerName" + ":" + "$version"
                
                Write-Host "Manually updating deployment with image: $fullImageName" -ForegroundColor Cyan
                kubectl set image "deployment/$deploymentName" "$containerName=$fullImageName" -n $Namespace
                
                if ($LASTEXITCODE -eq 0) {
                    # Wait for rollout
                    kubectl rollout status deployment/$deploymentName -n $Namespace --timeout=300s
                } else {
                    Write-Host "Failed to update deployment image manually" -ForegroundColor Red
                }
            }
        }
        catch {
            Write-Host "Error during build action: $_" -ForegroundColor Red
        }
    }
    
    "restart" {
        Write-Host "Restarting deployment..." -ForegroundColor Yellow
        
        # Restart the deployment (this recreates pods with same image)
        kubectl rollout restart deployment/$deploymentName -n $Namespace
        
        # Wait for rollout
        kubectl rollout status deployment/$deploymentName -n $Namespace --timeout=300s
        
        # Show status
        kubectl get pods -l app=respondr -n $Namespace
        
        Write-Host "Deployment restarted successfully" -ForegroundColor Green
    }
    
    "update-config" {
        Write-Host "Updating configuration..." -ForegroundColor Yellow
        
        # Check if secrets file exists
        $secretsFile = "$PSScriptRoot\secrets.yaml"
        if (Test-Path $secretsFile) {
            Write-Host "Applying updated secrets..." -ForegroundColor Yellow
            kubectl apply -f $secretsFile -n $Namespace
            
            # Restart deployment to pick up new config
            kubectl rollout restart deployment/$deploymentName -n $Namespace
            kubectl rollout status deployment/$deploymentName -n $Namespace --timeout=300s
            
            Write-Host "Configuration updated successfully" -ForegroundColor Green
        } else {
            Write-Host "No secrets.yaml file found at $secretsFile" -ForegroundColor Yellow
            Write-Host "Please ensure secrets are configured before running update-config" -ForegroundColor Yellow
        }
    }
}

Write-Host "`nCurrent deployment status:" -ForegroundColor Green
kubectl get deployment $deploymentName -n $Namespace
kubectl get pods -l app=respondr -n $Namespace

# Helper to debug failing pods if needed
if ($Action -eq "build") {
    $failingPods = kubectl get pods -l app=respondr -n $Namespace | Select-String "InvalidImageName|ImagePullBackOff|ErrImagePull"
    if ($failingPods) {
        Write-Host "`nDetected pods with image issues. Detailed information:" -ForegroundColor Red
        kubectl describe pods -l app=respondr -n $Namespace | Select-String -Context 10 "InvalidImageName|ImagePullBackOff|ErrImagePull"
    }
}
