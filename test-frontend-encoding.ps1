#!/usr/bin/env pwsh

# Quick test of just the frontend tests to check Unicode handling
Write-Host "Testing frontend test output encoding..." -ForegroundColor Yellow

Push-Location "frontend"
try {
    $env:CI = "true"
    $env:FORCE_COLOR = "0"
    $env:NO_COLOR = "1"
    
    Write-Host "Running frontend tests with encoding fixes..." -ForegroundColor Cyan
    
    # Test the npm test command
    npm test -- --watchAll=false --ci --verbose=false 2>&1 | ForEach-Object {
        $line = $_.ToString()
        # Replace problematic Unicode characters
        $line = $line -replace "✓", "[PASS]" -replace "✗", "[FAIL]" -replace "ΓêÜ", "[PASS]"
        Write-Host $line
    }
    
    $testResult = $LASTEXITCODE
    
    if ($testResult -eq 0) {
        Write-Host "Frontend tests completed successfully!" -ForegroundColor Green
    } else {
        Write-Host "Frontend tests failed with exit code $testResult" -ForegroundColor Red
    }
}
finally {
    Remove-Item Env:\CI -ErrorAction SilentlyContinue
    Remove-Item Env:\FORCE_COLOR -ErrorAction SilentlyContinue
    Remove-Item Env:\NO_COLOR -ErrorAction SilentlyContinue
    Pop-Location
}
