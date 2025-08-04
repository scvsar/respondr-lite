#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Run all tests for the Respondr application
    
.DESCRIPTION
    This script runs both backend (pytest) and frontend (jest) tests
    
.EXAMPLE
    .\run-tests.ps1
#>

$ErrorActionPreference = "Stop"

Write-Host "Respondr Test Runner" -ForegroundColor Green
Write-Host "===================" -ForegroundColor Green

# Check if Python is installed
try {
    $pythonVersion = python --version
    Write-Host "Using $pythonVersion" -ForegroundColor Cyan
}
catch {
    Write-Error "Python not found. Please install Python 3.8 or later."
    exit 1
}

# Check if Node.js is installed
try {
    $nodeVersion = node --version
    Write-Host "Using Node.js $nodeVersion" -ForegroundColor Cyan
}
catch {
    Write-Error "Node.js not found. Please install Node.js 14 or later."
    exit 1
}

# Function to run tests with proper error handling
function Run-Tests {
    param (
        [string]$Name,
        [string]$Command,
        [string]$WorkingDirectory
    )
    
    Write-Host "`n$Name Tests" -ForegroundColor Yellow
    Write-Host ("-" * ($Name.Length + 6)) -ForegroundColor Yellow
    
    Push-Location $WorkingDirectory
    try {
        # Install dependencies if needed
        if ($Name -eq "Frontend" -and !(Test-Path "node_modules")) {
            Write-Host "Installing frontend dependencies..." -ForegroundColor Cyan
            npm install | Out-Host
            if ($LASTEXITCODE -ne 0) {
                Write-Host "Failed to install frontend dependencies" -ForegroundColor Red
                return $false
            }
        }
        elseif ($Name -eq "Backend" -and (Test-Path "requirements.txt")) {
            # Check if we need to install backend dependencies
            $requirementsContent = Get-Content "requirements.txt" -Raw
            $missingDeps = $false
            try {
                # Try importing fastapi as a test for installed dependencies
                python -c "import fastapi" 2>$null
                if ($LASTEXITCODE -ne 0) {
                    $missingDeps = $true
                }
            }
            catch {
                $missingDeps = $true
            }
            
            if ($missingDeps) {
                Write-Host "Installing backend dependencies..." -ForegroundColor Cyan
                pip install -r requirements.txt | Out-Host
                if ($LASTEXITCODE -ne 0) {
                    Write-Host "Failed to install backend dependencies" -ForegroundColor Red
                    return $false
                }
            }
        }
        
        # Special handling for npm tests to prevent hanging
        if ($Command -like "*npm test*") {
            # Use CI=true environment variable to force non-interactive mode
            $env:CI = "true"
            # Run npm test with explicit exit and redirect output to host
            Invoke-Expression "$Command 2>&1" | Out-Host
        } else {
            # Run normal command and redirect output to host
            Invoke-Expression "$Command 2>&1" | Out-Host
        }
        
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Tests failed with exit code $LASTEXITCODE" -ForegroundColor Red
            return $false
        }
        Write-Host "All tests passed!" -ForegroundColor Green
        return $true
    }
    catch {
        Write-Host "Error running tests: $_" -ForegroundColor Red
        return $false
    }
    finally {
        # Reset CI environment variable
        if ($Command -like "*npm test*") {
            Remove-Item Env:\CI -ErrorAction SilentlyContinue
        }
        Pop-Location
    }
}

# Run backend tests
$backendSuccess = Run-Tests -Name "Backend" -Command "python run_tests.py" -WorkingDirectory ".\backend"

# Run frontend tests
$frontendSuccess = Run-Tests -Name "Frontend" -Command "npm test -- --watchAll=false --ci" -WorkingDirectory ".\frontend"

# Report overall status
Write-Host "`nTest Summary" -ForegroundColor Yellow
Write-Host "===========" -ForegroundColor Yellow

if ($backendSuccess) {
    Write-Host "Backend Tests: PASSED" -ForegroundColor Green
}
else {
    Write-Host "Backend Tests: FAILED" -ForegroundColor Red
}

if ($frontendSuccess) {
    Write-Host "Frontend Tests: PASSED" -ForegroundColor Green
}
else {
    Write-Host "Frontend Tests: FAILED" -ForegroundColor Red
}

if ($backendSuccess -and $frontendSuccess) {
    Write-Host "`nAll tests passed successfully!" -ForegroundColor Green
    exit 0
}
else {
    Write-Host "`nSome tests failed." -ForegroundColor Red
    exit 1
}
