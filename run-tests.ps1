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
if ($PSVersionTable.PSVersion.Major -ge 6) {
    # PowerShell 6+ (cross-platform)
    $PSDefaultParameterValues['Out-File:Encoding'] = 'utf8'
    $PSDefaultParameterValues['*:Encoding'] = 'utf8'
} else {
    # Windows PowerShell 5.1 and earlier
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    [Console]::InputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
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
        Write-Host "✅ Using $pythonVersion" -ForegroundColor Green
    }
    catch {
        Write-Host "❌ Python not found. Please install Python 3.8 or later." -ForegroundColor Red
        $allGood = $false
    }

    # Check if Node.js is installed
    try {
        $nodeVersion = node --version
        Write-Host "✅ Using Node.js $nodeVersion" -ForegroundColor Green
    }
    catch {
        Write-Host "❌ Node.js not found. Please install Node.js 14 or later." -ForegroundColor Red
        $allGood = $false
    }

    # Check if we're in the right directory
    if (!(Test-Path "backend") -or !(Test-Path "frontend")) {
        Write-Host "❌ Backend or frontend directory not found. Make sure you're in the respondr project root." -ForegroundColor Red
        $allGood = $false
    } else {
        Write-Host "✅ Project structure found" -ForegroundColor Green
    }

    # Check backend virtual environment and dependencies
    if (Test-Path "backend") {
        Push-Location "backend"
        try {
            # Check if virtual environment is active or available
            if ($env:VIRTUAL_ENV) {
                Write-Host "✅ Virtual environment active: $env:VIRTUAL_ENV" -ForegroundColor Green
            } elseif (Test-Path ".venv") {
                Write-Host "⚠️  Virtual environment found but not active. Activating..." -ForegroundColor Yellow
                & ".\.venv\Scripts\Activate.ps1"
                Write-Host "✅ Virtual environment activated" -ForegroundColor Green
            } else {
                Write-Host "⚠️  No virtual environment found. Please run setup_local_env.py first." -ForegroundColor Yellow
            }

            # Check if FastAPI can be imported (indicating dependencies are installed)
            python -c "import fastapi" 2>$null
            if ($LASTEXITCODE -eq 0) {
                Write-Host "✅ Backend dependencies installed" -ForegroundColor Green
            } else {
                Write-Host "⚠️  Backend dependencies may need to be installed" -ForegroundColor Yellow
            }

            # Check if .env file exists
            if (Test-Path ".env") {
                Write-Host "✅ Backend .env file found" -ForegroundColor Green
            } else {
                Write-Host "⚠️  Backend .env file not found. Some tests may use default values." -ForegroundColor Yellow
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
                Write-Host "✅ Frontend dependencies installed" -ForegroundColor Green
            } else {
                Write-Host "⚠️  Frontend dependencies need to be installed" -ForegroundColor Yellow
            }

            if (Test-Path "package.json") {
                Write-Host "✅ Frontend package.json found" -ForegroundColor Green
            } else {
                Write-Host "❌ Frontend package.json not found" -ForegroundColor Red
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
    Write-Host "`n❌ Prerequisites not met. Please fix the issues above before running tests." -ForegroundColor Red
    exit 1
}

Write-Host "`n✅ All prerequisites met. Starting tests..." -ForegroundColor Green

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
        
        # Special handling for npm tests to prevent hanging and preserve Unicode output
        if ($Command -like "*npm test*") {
            # Use CI=true environment variable to force non-interactive mode
            $env:CI = "true"
            # Run npm test with explicit exit, preserving Unicode characters
            if ($PSVersionTable.PSVersion.Major -ge 6) {
                # PowerShell 6+ handles UTF-8 better
                Invoke-Expression "$Command 2>&1" | Out-Host
            } else {
                # Windows PowerShell 5.1 - use Start-Process for better Unicode handling
                $processInfo = New-Object System.Diagnostics.ProcessStartInfo
                $processInfo.FileName = "cmd.exe"
                $processInfo.Arguments = "/c `"$Command`""
                $processInfo.UseShellExecute = $false
                $processInfo.RedirectStandardOutput = $true
                $processInfo.RedirectStandardError = $true
                $processInfo.StandardOutputEncoding = [System.Text.Encoding]::UTF8
                $processInfo.StandardErrorEncoding = [System.Text.Encoding]::UTF8
                $processInfo.WorkingDirectory = Get-Location
                
                $process = New-Object System.Diagnostics.Process
                $process.StartInfo = $processInfo
                $process.Start() | Out-Null
                
                # Read output with proper encoding
                $output = $process.StandardOutput.ReadToEnd()
                $errorOutput = $process.StandardError.ReadToEnd()
                $process.WaitForExit()
                
                # Display output
                if ($output) { Write-Host $output -NoNewline }
                if ($errorOutput) { Write-Host $errorOutput -NoNewline }
                
                # Set exit code for error handling
                $global:LASTEXITCODE = $process.ExitCode
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
