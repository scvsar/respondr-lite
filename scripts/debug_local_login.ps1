$body = @{
    email = "test@example.com"
    password = "TestPass123!"
}

try {
    $resp = Invoke-RestMethod -Uri "http://localhost:7071/api/local_login" -Method Post -Body ($body | ConvertTo-Json) -ContentType "application/json"
    Write-Host "Status: 200" -ForegroundColor Green
    $resp | ConvertTo-Json -Depth 5 | Write-Host
} catch {
    Write-Host "Request failed: $($_.Exception.Message)" -ForegroundColor Red
    if ($_.Exception.Response -and $_.Exception.Response.GetResponseStream) {
        $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
        $bodyText = $reader.ReadToEnd()
        Write-Host "Response body:" -ForegroundColor Yellow
        Write-Host $bodyText
    }
}
