param(
    [string]$BaseUrl = "https://respondr.scvsar.org",
    [string]$ApiKey
)

if (-not $ApiKey) {
    Write-Error "Provide -ApiKey (WEBHOOK_API_KEY for the deployment)."
    exit 1
}

$Headers = @{ 'X-API-Key' = $ApiKey }
$Url = "$BaseUrl/api/clear-all"

Write-Host "Clearing all responder data at $Url ..."
try {
    $resp = Invoke-RestMethod -Method Post -Uri $Url -Headers $Headers -ErrorAction Stop
    Write-Host "Success:" ($resp | ConvertTo-Json -Depth 5)
}
catch {
    Write-Error $_
    exit 1
}
