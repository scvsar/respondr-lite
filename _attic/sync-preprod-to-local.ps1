#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Sync preprod Redis data to local Redis for analysis

.DESCRIPTION
    Copies Redis data from preprod to local Redis for testing and analysis
#>

param(
    [string]$PreprodNamespace = "respondr-preprod",
    [string]$PreprodService = "redis-service",
    [string]$LocalRedisHost = "localhost",
    [string]$LocalRedisPort = "6379"
)

$ErrorActionPreference = "Stop"

Write-Host "🔄 Syncing Redis data from preprod to local" -ForegroundColor Cyan

# Pre-checks
if (-not (Get-Command kubectl -ErrorAction SilentlyContinue)) {
    Write-Error "kubectl not found in PATH"
    exit 1
}

# Check if local Redis is running
try {
    $null = redis-cli -h $LocalRedisHost -p $LocalRedisPort ping
    Write-Host "✅ Local Redis is running at $LocalRedisHost:$LocalRedisPort" -ForegroundColor Green
} catch {
    Write-Error "❌ Local Redis not accessible at $LocalRedisHost:$LocalRedisPort. Please start Redis locally."
    exit 1
}

$sourceHost = "$PreprodService.$PreprodNamespace.svc.cluster.local"
$targetHost = $LocalRedisHost
$sourcePort = 6379
$targetPort = $LocalRedisPort

Write-Host "Source Redis: $sourceHost:$sourcePort"
Write-Host "Target Redis: $targetHost:$targetPort"

# Keys to copy
$keys = @("respondr_messages", "respondr_deleted_messages")
Write-Host "Keys to copy: $($keys -join ', ')"

# Find a Redis pod in preprod namespace to use as client
$preprodPods = kubectl get pods -n $PreprodNamespace -l app=redis -o jsonpath='{.items[0].metadata.name}' 2>$null
if ([string]::IsNullOrWhiteSpace($preprodPods)) {
    Write-Error "No Redis pods found in namespace '$PreprodNamespace'"
    exit 1
}

Write-Host "Using preprod Redis pod: $preprodPods"

foreach ($key in $keys) {
    Write-Host "Copying key: $key"
    
    # Get data from preprod Redis
    $data = kubectl exec -n $PreprodNamespace $preprodPods -- redis-cli -h $sourceHost -p $sourcePort GET $key 2>$null
    
    if ([string]::IsNullOrWhiteSpace($data) -or $data -eq "(nil)") {
        Write-Host "Source key $key not found; skipping" -ForegroundColor Yellow
        continue
    }
    
    # Write to local Redis using redis-cli
    $tempFile = [System.IO.Path]::GetTempFileName()
    try {
        # Write the data to a temp file to handle special characters
        $data | Out-File -FilePath $tempFile -Encoding UTF8 -NoNewline
        
        # Use redis-cli to set the data locally
        $result = redis-cli -h $LocalRedisHost -p $LocalRedisPort -x SET $key < $tempFile
        
        if ($result -eq "OK") {
            Write-Host "✅ Copied $key successfully" -ForegroundColor Green
        } else {
            Write-Host "❌ Failed to copy $key: $result" -ForegroundColor Red
        }
    } finally {
        Remove-Item $tempFile -ErrorAction SilentlyContinue
    }
}

Write-Host ""
Write-Host "✅ Sync complete" -ForegroundColor Green
Write-Host "💡 You can now analyze the preprod data locally using:"
Write-Host "   python check_preprod_redis.py"
