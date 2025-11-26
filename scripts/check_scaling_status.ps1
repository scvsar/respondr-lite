param(
    [string]$ResourceGroup = "respondr-ppe-eastus2",
    [string]$ContainerAppName = "respondrlite-ca-afb70ccc",
    [string]$StorageAccountName = "respondrlitesgb62d1b85",
    [string]$QueueName = "respondr-incoming"
)

$ErrorActionPreference = "Stop"

Write-Host "Checking Scaling Status for '$ContainerAppName'..." -ForegroundColor Cyan

# 1. Get Container App Details (ID and Cooldown)
Write-Host "   Getting Container App configuration..." -NoNewline
# Use az resource show to ensure we get all properties including cooldownPeriod
$ca = az resource show -g $ResourceGroup -n $ContainerAppName --resource-type Microsoft.App/containerApps -o json | ConvertFrom-Json
$caId = $ca.id
# Access the cooldown period correctly from the JSON structure
$cooldownSeconds = $ca.properties.template.scale.cooldownPeriod
if ($null -eq $cooldownSeconds) { 
    Write-Host " (Not found in properties, using default 300)" -NoNewline -ForegroundColor DarkGray
    $cooldownSeconds = 300 
}
Write-Host " Done." -ForegroundColor Green
Write-Host "   Configured Cooldown Period: $cooldownSeconds seconds ($([math]::Round($cooldownSeconds/60, 1)) minutes)" -ForegroundColor Gray

# 2. Check Current Replica Count
Write-Host "`nChecking Current Replica Count..." -NoNewline
# Method A: Metrics (Historical/Lagging)
$metricReplicas = az monitor metrics list --resource $caId --metric "Replicas" --interval PT1M --offset 5m --output json | ConvertFrom-Json
$metricCount = 0
if ($metricReplicas.value[0].timeseries[0].data.Count -gt 0) {
    $lastData = $metricReplicas.value[0].timeseries[0].data | Select-Object -Last 1
    $metricCount = $lastData.maximum
}

# Method B: Real-time API (Accurate)
$latestRevision = $ca.properties.latestRevisionName
$realtimeReplicas = az containerapp replica list -n $ContainerAppName -g $ResourceGroup --revision $latestRevision -o json | ConvertFrom-Json
$currentReplicas = $realtimeReplicas.Count
$replicaStartTime = $null

if ($currentReplicas -gt 0) {
    # Get the start time of the first replica
    $replicaStartTime = [DateTimeOffset]::Parse($realtimeReplicas[0].properties.createdTime).UtcDateTime
}

Write-Host " Done." -ForegroundColor Green
Write-Host "   Current Replicas (Real-time): $currentReplicas" -ForegroundColor Yellow
if ($replicaStartTime) {
    $minsRunning = [math]::Round(((Get-Date).ToUniversalTime() - $replicaStartTime).TotalMinutes, 1)
    Write-Host "   Replica Started: $replicaStartTime UTC ($minsRunning minutes ago)" -ForegroundColor Yellow
}
if ($metricCount -ne $currentReplicas) {
    Write-Host "   (Metrics report $metricCount, but they may be lagging)" -ForegroundColor DarkGray
}

# 3. Check Last HTTP Activity (Requests metric)
Write-Host "`nChecking Last HTTP Activity (scanning last 4 hours)..." -NoNewline
# Scan last 4 hours to cover the 2h cooldown window safely
$metricRequests = az monitor metrics list --resource $caId --metric "Requests" --interval PT1M --offset 4h --output json | ConvertFrom-Json
$dataPoints = $metricRequests.value[0].timeseries[0].data
$lastRequestTime = $null

# Iterate backwards to find last non-zero request
for ($i = $dataPoints.Count - 1; $i -ge 0; $i--) {
    if ($dataPoints[$i].total -gt 0) {
        # Use DateTimeOffset to correctly handle ISO 8601 with Z
        $lastRequestTime = [DateTimeOffset]::Parse($dataPoints[$i].timeStamp).UtcDateTime
        break
    }
}

Write-Host " Done." -ForegroundColor Green
$nowUtc = (Get-Date).ToUniversalTime()
Write-Host "   Current Time (UTC): $nowUtc" -ForegroundColor Gray

if ($lastRequestTime) {
    $timeSinceRequest = $nowUtc - $lastRequestTime
    $minsAgo = [math]::Round($timeSinceRequest.TotalMinutes, 1)
    Write-Host "   Last Request: $lastRequestTime UTC ($minsAgo minutes ago)" -ForegroundColor Yellow
} else {
    Write-Host "   Last Request: None in the last 4 hours" -ForegroundColor Yellow
    $timeSinceRequest = [TimeSpan]::FromHours(4) # Treat as long ago
}

# 4. Check Storage Queue Length
Write-Host "`nChecking Storage Queue Length..." -NoNewline
# Get connection string for reliable access
$connStr = az storage account show-connection-string -g $ResourceGroup -n $StorageAccountName --query connectionString -o tsv
# Get queue stats
$queueStats = az storage queue metadata show --name $QueueName --connection-string $connStr -o json | ConvertFrom-Json
$messageCount = $queueStats.approximateMessagesCount
if ($null -eq $messageCount) { $messageCount = 0 }
Write-Host " Done." -ForegroundColor Green
Write-Host "   Queue '$QueueName' Length: $messageCount" -ForegroundColor Yellow

# 5. Analysis & Summary
Write-Host "`nANALYSIS" -ForegroundColor Cyan
Write-Host "----------------------------------------"

$shouldBeActive = $false
$reasons = @()

# Check Queue Trigger
if ($messageCount -gt 0) {
    $shouldBeActive = $true
    $reasons += "Queue has $messageCount messages (waiting for processing)"
} else {
    $reasons += "Queue is empty"
}

# Check HTTP Trigger (Cooldown)
$secondsSinceRequest = $timeSinceRequest.TotalSeconds

# If we have a running replica that started RECENTLY (after the last known request metric), 
# use that as a proxy for "Last Activity" to avoid stale metric confusion.
if ($replicaStartTime -and $replicaStartTime -gt $lastRequestTime) {
    $secondsSinceStart = ((Get-Date).ToUniversalTime() - $replicaStartTime).TotalSeconds
    if ($secondsSinceStart -lt $secondsSinceRequest) {
        $secondsSinceRequest = $secondsSinceStart
        $timeSinceRequest = [TimeSpan]::FromSeconds($secondsSinceStart)
        Write-Host "   (Using Replica Start Time as proxy for Last Activity due to metric lag)" -ForegroundColor DarkGray
    }
}

if ($secondsSinceRequest -lt $cooldownSeconds) {
    $shouldBeActive = $true
    $remaining = [math]::Round(($cooldownSeconds - $secondsSinceRequest) / 60, 1)
    $minSince = [math]::Round($secondsSinceRequest/60, 1)
    $minCooldown = [math]::Round($cooldownSeconds/60, 1)
    $msg = "Within HTTP cooldown window (Last request was {0} min ago, cooldown is {1} min). Scaling down in ~{2} min." -f $minSince, $minCooldown, $remaining
    $reasons += $msg
} else {
    $minSince = [math]::Round($secondsSinceRequest/60, 1)
    $minCooldown = [math]::Round($cooldownSeconds/60, 1)
    $msg = "HTTP cooldown period expired ({0} min > {1} min)" -f $minSince, $minCooldown
    $reasons += $msg
}

# Conclusion
Write-Host "Expected State: " -NoNewline
if ($shouldBeActive) {
    Write-Host "ACTIVE (>0 Replicas)" -ForegroundColor Green
} else {
    Write-Host "IDLE (0 Replicas)" -ForegroundColor Blue
}

Write-Host "Actual State:   " -NoNewline
if ($currentReplicas -gt 0) {
    Write-Host "ACTIVE ($currentReplicas Replicas)" -ForegroundColor Green
} else {
    Write-Host "IDLE (0 Replicas)" -ForegroundColor Blue
}

Write-Host "`nDetails:"
foreach ($r in $reasons) {
    Write-Host " - $r"
}

Write-Host "----------------------------------------"
if ($shouldBeActive -eq ($currentReplicas -gt 0)) {
    Write-Host "System is behaving as expected." -ForegroundColor Green
} else {
    if ($shouldBeActive -and $currentReplicas -eq 0) {
        Write-Host "WARNING: System should be active but is scaled to zero!" -ForegroundColor Red
    } elseif (-not $shouldBeActive -and $currentReplicas -gt 0) {
        Write-Host "WARNING: System should be idle but is still running." -ForegroundColor Red
        Write-Host "   (Note: It may take a few minutes for the scaler to react after the cooldown expires)" -ForegroundColor Gray
    }
}
