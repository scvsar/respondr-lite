# Seed webhook with test data
$messages = @(
    @{ name = 'John Smith'; text = 'Responding with SAR78 ETA 15 minutes'; minsAgo = 6 },
    @{ name = 'Sarah Johnson'; text = 'Taking POV, should be there by 23:30'; minsAgo = 5 },
    @{ name = 'Mike Rodriguez'; text = 'I will take SAR-4, ETA 20 mins'; minsAgo = 4 },
    @{ name = 'Lisa Chen'; text = 'Responding in my personal vehicle, about 25 minutes out'; minsAgo = 3 },
    @{ name = 'Grace Lee'; text = 'Hey team, just checking the weather up there'; minsAgo = 2 }
)

Write-Host "Seeding webhook with test data..." -ForegroundColor Green

foreach ($m in $messages) {
    $ts = [int]([DateTimeOffset]::UtcNow.ToUnixTimeSeconds()) - ($m.minsAgo * 60)
    $body = @{
        attachments = @()
        avatar_url = 'https://i.groupme.com/1024x1024.jpeg.placeholder'
        created_at = $ts
        group_id = '123456789'
        id = [string]([int64]([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()))
        name = $m.name
        sender_id = '30001234'
        sender_type = 'user'
        source_guid = ([guid]::NewGuid().ToString().ToUpper())
        system = $false
        text = $m.text
        user_id = '30001234'
    } | ConvertTo-Json -Depth 6
    
    try {
        $response = Invoke-RestMethod -Uri 'http://localhost:8000/webhook' -Method Post -ContentType 'application/json' -Body $body -TimeoutSec 15
        Write-Host "✓ Sent: $($m.name)" -ForegroundColor Green
    } catch {
        Write-Host "✗ Failed: $($m.name) - $($_.Exception.Message)" -ForegroundColor Red
    }
}

Write-Host "`nChecking responders..." -ForegroundColor Yellow
try {
    $resp = Invoke-RestMethod -Uri 'http://localhost:8000/api/responders' -TimeoutSec 15
    Write-Host "Responders count: $($resp.Count)" -ForegroundColor Cyan
    if ($resp.Count -gt 0) {
        Write-Host "Sample responder:" -ForegroundColor Yellow
        $resp[0] | ConvertTo-Json -Depth 3
    }
} catch {
    Write-Host "Failed to get responders: $($_.Exception.Message)" -ForegroundColor Red
}
