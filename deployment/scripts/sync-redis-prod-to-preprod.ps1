#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Sync prod Redis data into preprod Redis inside the AKS cluster.

.DESCRIPTION
    Copies the two JSON keys used by Respondr:
      - respondr_messages
      - respondr_deleted_messages

    Runs an ephemeral redis:7-alpine pod in the target namespace and uses redis-cli
    to read from the prod service (respondr) and write to the preprod service.

.PARAMETER SourceNamespace
    Kubernetes namespace for prod Redis (default: respondr)

.PARAMETER TargetNamespace
    Kubernetes namespace for preprod Redis (default: respondr-preprod)

.PARAMETER SourceService
    Service name for prod Redis (default: redis-service)

.PARAMETER TargetService
    Service name for preprod Redis (default: redis-service)

.EXAMPLE
    .\scripts\sync-redis-prod-to-preprod.ps1

.EXAMPLE
    .\scripts\sync-redis-prod-to-preprod.ps1 -SourceNamespace respondr -TargetNamespace respondr-preprod
#>

param(
    [string]$SourceNamespace = "respondr",
    [string]$TargetNamespace = "respondr-preprod",
    [string]$SourceService = "redis-service",
    [string]$TargetService = "redis-service"
)

$ErrorActionPreference = "Stop"

Write-Host "🔁 Syncing Redis data from '$SourceNamespace' -> '$TargetNamespace'" -ForegroundColor Cyan

# Pre-checks
if (-not (Get-Command kubectl -ErrorAction SilentlyContinue)) {
    Write-Error "kubectl not found in PATH"
    exit 1
}

try {
    kubectl cluster-info --request-timeout=5s | Out-Null
} catch {
    Write-Error "Cannot connect to Kubernetes cluster. Check kubeconfig context."
    exit 1
}

# Compose in-cluster DNS names for the Redis services
$srcHost = "${SourceService}.${SourceNamespace}.svc.cluster.local"
$dstHost = "${TargetService}.${TargetNamespace}.svc.cluster.local"

Write-Host ("Source Redis: {0}:6379" -f $srcHost) -ForegroundColor Yellow
Write-Host ("Target Redis: {0}:6379" -f $dstHost) -ForegroundColor Yellow

# Ensure target namespace exists
$nsExists = kubectl get ns $TargetNamespace 2>$null
if (-not $nsExists) {
    Write-Error "Target namespace '$TargetNamespace' not found."
    exit 1
}

# Keys to copy
$keys = @('respondr_messages', 'respondr_deleted_messages')
Write-Host "Keys to copy: $($keys -join ', ')" -ForegroundColor Yellow

# Find the target Redis pod (use label app=redis)
$targetPod = kubectl get pods -n $TargetNamespace -l app=redis -o jsonpath='{.items[0].metadata.name}' 2>$null
if (-not $targetPod) {
    Write-Error "No Redis pod found in target namespace '$TargetNamespace' (label app=redis). Ensure redis-deployment.yaml is applied."
    exit 1
}
Write-Host "Target Redis pod: $targetPod" -ForegroundColor Yellow

# Execute per-key copy inside the target Redis pod to avoid CRLF issues
foreach ($k in $keys) {
    Write-Host ("Copying key: {0}" -f $k) -ForegroundColor Yellow
    $oneLinerTemplate = @'
SRC="__SRC__"; KEY="__KEY__"; if redis-cli -h "$SRC" -p 6379 EXISTS "$KEY" | grep -q '^1$'; then TTL=$(redis-cli -h "$SRC" -p 6379 TTL "$KEY" || echo -1); VAL=$(redis-cli -h "$SRC" -p 6379 --raw GET "$KEY"); if [ -n "$VAL" ]; then if [ "$TTL" -ge 0 ] 2>/dev/null; then printf "%s" "$VAL" | redis-cli -h 127.0.0.1 -p 6379 -x SETEX "$KEY" "$TTL"; echo "Copied $KEY with TTL=$TTL"; else printf "%s" "$VAL" | redis-cli -h 127.0.0.1 -p 6379 -x SET "$KEY"; echo "Copied $KEY with no expiry"; fi; else printf "%s" "" | redis-cli -h 127.0.0.1 -p 6379 -x SET "$KEY"; echo "Copied empty $KEY"; fi; else echo "Source key $KEY not found; skipping"; fi
'@
    $oneLiner = $oneLinerTemplate.Replace('__SRC__', $srcHost).Replace('__KEY__', $k)

    $args = @('exec','-n', $TargetNamespace, $targetPod,'-c','redis','--','sh','-c', $oneLiner)
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = 'kubectl'
    foreach ($arg in $args) { [void]$psi.ArgumentList.Add($arg) }
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.UseShellExecute = $false
    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi
    $null = $proc.Start()
    $out = $proc.StandardOutput.ReadToEnd()
    $err = $proc.StandardError.ReadToEnd()
    $proc.WaitForExit()
    if ($out) { Write-Host $out }
    if ($err) { Write-Host $err -ForegroundColor DarkYellow }
    if ($proc.ExitCode -ne 0) {
        Write-Error ("Failed copying key {0} (exit {1})" -f $k, $proc.ExitCode)
        exit $proc.ExitCode
    }
}

Write-Host "✅ Sync complete" -ForegroundColor Green
