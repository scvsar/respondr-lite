#!/usr/bin/env pwsh

# Test script to check character encoding support
Write-Host "Testing character encoding..." -ForegroundColor Yellow

# Test various characters
Write-Host "ASCII check mark: [v]"
Write-Host "ASCII cross mark: [X]"
Write-Host "ASCII warning: [!]"

# Test if Unicode works
try {
    $checkMark = "✅"
    $crossMark = "❌" 
    $warningMark = "⚠️"
    
    Write-Host "Unicode check mark: $checkMark"
    Write-Host "Unicode cross mark: $crossMark"
    Write-Host "Unicode warning: $warningMark"
    
    # Test if the terminal properly displays these
    $testString = "$checkMark $crossMark $warningMark"
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($testString)
    Write-Host "Test string byte length: $($bytes.Length)"
    Write-Host "Test string char length: $($testString.Length)"
    
    if ($bytes.Length -gt $testString.Length) {
        Write-Host "Unicode characters detected - multi-byte encoding" -ForegroundColor Green
    } else {
        Write-Host "ASCII characters only" -ForegroundColor Yellow
    }
}
catch {
    Write-Host "Unicode test failed: $_" -ForegroundColor Red
}

Write-Host "`nCurrent console encoding:"
Write-Host "Output encoding: $([Console]::OutputEncoding.EncodingName)"
Write-Host "PowerShell version: $($PSVersionTable.PSVersion)"
