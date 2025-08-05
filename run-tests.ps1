#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Run all tests for the Respondr application
    
.DESCRIPTION
    This script runs both backend (pytest) and frontend (jest) tests with comprehensive prerequisite checks
    
.EXAMPLE
    .\run-tests.ps1
#>

$ErrorActionPreference = "Stop"

# Set console encoding to UTF-8 to properly display Unicode characters like checkmarks
# Use simple ASCII characters instead of Unicode for better compatibility
$script:checkMark = "√"
$script:crossMark = "X"
$script:warningMark = "!"

# Try to set UTF-8 encoding, but fall back gracefully
try {
    if ($PSVersionTable.PSVersion.Major -ge 6) {
        # PowerShell 6+ (cross-platform)
        $PSDefaultParameterValues['Out-File:Encoding'] = 'utf8'
        $PSDefaultParameterValues['*:Encoding'] = 'utf8'
        # Use proper Unicode characters in PowerShell Core
        $script:checkMark = "✅"
        $script:crossMark = "❌"
        $script:warningMark = "⚠️"
    } else {
        # Windows PowerShell 5.1 and earlier - be more conservative
        [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
        $OutputEncoding = [System.Text.Encoding]::UTF8
        # Test if Unicode works
        $testOutput = "✅"
        if ([Console]::OutputEncoding.GetBytes($testOutput).Length -eq $testOutput.Length) {
            # Unicode likely supported
            $script:checkMark = "✅"
            $script:crossMark = "❌"
            $script:warningMark = "⚠️"
        }
    }
}
catch {
    # Fall back to ASCII characters if encoding setup fails
    Write-Warning "Unicode display may not work properly. Using ASCII characters."
}

Write-Host "Respondr Test Runner" -ForegroundColor Green
Write-Host "===================" -ForegroundColor Green

# Function to check prerequisites
function Test-Prerequisites {
    $allGood = $true
    
    Write-Host "Checking prerequisites..." -ForegroundColor Yellow
    
    # Check if Python is installed
    try {
        $pythonVersion = python --version
        Write-Host "$script:checkMark Using $pythonVersion" -ForegroundColor Green
    }
    catch {
        Write-Host "$script:crossMark Python not found. Please install Python 3.8 or later." -ForegroundColor Red
        $allGood = $false
    }

    # Check if Node.js is installed
    try {
        $nodeVersion = node --version
        Write-Host "$script:checkMark Using Node.js $nodeVersion" -ForegroundColor Green
    }
    catch {
        Write-Host "$script:crossMark Node.js not found. Please install Node.js 14 or later." -ForegroundColor Red
        $allGood = $false
    }

    # Check if we're in the right directory
    if (!(Test-Path "backend") -or !(Test-Path "frontend")) {
        Write-Host "$script:crossMark Backend or frontend directory not found. Make sure you're in the respondr project root." -ForegroundColor Red
        $allGood = $false
    } else {
        Write-Host "$script:checkMark Project structure found" -ForegroundColor Green
    }

    # Check backend virtual environment and dependencies
    if (Test-Path "backend") {
        Push-Location "backend"
        try {
            # Check if virtual environment is active or available
            if ($env:VIRTUAL_ENV) {
                Write-Host "$script:checkMark Virtual environment active: $env:VIRTUAL_ENV" -ForegroundColor Green
            } elseif (Test-Path ".venv") {
                Write-Host "$script:warningMark Virtual environment found but not active. Activating..." -ForegroundColor Yellow
                & ".\.venv\Scripts\Activate.ps1"
                Write-Host "$script:checkMark Virtual environment activated" -ForegroundColor Green
            } else {
                Write-Host "$script:warningMark No virtual environment found. Please run setup_local_env.py first." -ForegroundColor Yellow
            }

            # Check if FastAPI can be imported (indicating dependencies are installed)
            python -c "import fastapi" 2>$null
            if ($LASTEXITCODE -eq 0) {
                Write-Host "$script:checkMark Backend dependencies installed" -ForegroundColor Green
            } else {
                Write-Host "$script:warningMark Backend dependencies may need to be installed" -ForegroundColor Yellow
            }

            # Check if .env file exists
            if (Test-Path ".env") {
                Write-Host "$script:checkMark Backend .env file found" -ForegroundColor Green
            } else {
                Write-Host "$script:warningMark Backend .env file not found. Some tests may use default values." -ForegroundColor Yellow
            }
        }
        finally {
            Pop-Location
        }
    }

    # Check frontend dependencies
    if (Test-Path "frontend") {
        Push-Location "frontend"
        try {
            if (Test-Path "node_modules") {
                Write-Host "$script:checkMark Frontend dependencies installed" -ForegroundColor Green
            } else {
                Write-Host "$script:warningMark Frontend dependencies need to be installed" -ForegroundColor Yellow
            }

            if (Test-Path "package.json") {
                Write-Host "$script:checkMark Frontend package.json found" -ForegroundColor Green
            } else {
                Write-Host "$script:crossMark Frontend package.json not found" -ForegroundColor Red
                $allGood = $false
            }
        }
        finally {
            Pop-Location
        }
    }

    return $allGood
}

# Run prerequisite checks
if (!(Test-Prerequisites)) {
    Write-Host "`n$script:crossMark Prerequisites not met. Please fix the issues above before running tests." -ForegroundColor Red
    exit 1
}

Write-Host "`n$script:checkMark All prerequisites met. Starting tests..." -ForegroundColor Green

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
        
        # Special handling for npm tests to prevent hanging and fix Unicode display issues
        if ($Command -like "*npm test*") {
            # Use CI=true environment variable to force non-interactive mode
            $env:CI = "true"
            
            Write-Host "Running Respondr frontend tests..." -ForegroundColor Cyan
            
            # Run the command and capture output, then filter Unicode issues
            $output = & cmd /c "cd /d `"$(Get-Location)`" && $Command 2>&1"
            
            # Process each line to fix Unicode display issues
            $output | ForEach-Object {
                $line = $_.ToString()
                # Replace problematic Unicode characters with readable alternatives
                $line = $line -replace "✓", "[√]" -replace "✗", "[X]" -replace "ΓêÜ", "[√]" -replace "Γ£ê", "[√]"
                Write-Host $line
            }
            
            # Check the exit code
            if ($LASTEXITCODE -ne 0) {
                Write-Host "Frontend tests failed with exit code $LASTEXITCODE" -ForegroundColor Red
                return $false
            }
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
