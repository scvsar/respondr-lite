#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Quick redeploy script for Respondr application

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
    .\redeploy.ps1 -Action "build" -ResourceGroupName "respondr-rg"
    
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
        
        # Call the main upgrade script
        & "$PSScriptRoot\upgrade-k8s.ps1" -Version $version -ResourceGroupName $ResourceGroupName -Namespace $Namespace
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
