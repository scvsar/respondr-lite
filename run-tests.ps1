#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Run the curated backend and frontend tests.
.EXAMPLE
    .\run-tests.ps1
#>
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$previousCI = [Environment]::GetEnvironmentVariable('CI', 'Process')

function Find-Python {
    $candidates = @()
    if ($env:VIRTUAL_ENV) {
        $candidates += Join-Path $env:VIRTUAL_ENV 'Scripts' 'python.exe'
        $candidates += Join-Path $env:VIRTUAL_ENV 'bin' 'python'
    }
    foreach ($directory in @((Join-Path $PSScriptRoot 'backend' '.venv'), (Join-Path $PSScriptRoot '.venv'))) {
        $candidates += Join-Path $directory 'Scripts' 'python.exe'
        $candidates += Join-Path $directory 'bin' 'python'
    }
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    foreach ($name in @('python', 'python3')) {
        $command = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue
        if ($command) { return $command.Source }
    }
    throw 'Install Python 3.11 or later.'
}

function Run-Tests {
    param([string]$Name, [string]$Directory, [scriptblock]$Action)
    Write-Host "Running $Name tests..."
    Push-Location $Directory
    try {
        $success = & $Action
        if (-not $success) { Write-Host "$Name tests failed." }
        return [bool]$success
    }
    catch {
        Write-Host "$Name tests failed: $_"
        return $false
    }
    finally { Pop-Location }
}

Push-Location $PSScriptRoot
try {
    $python = Find-Python
    $pythonVersion = & $python -c 'import sys; print(".".join(map(str, sys.version_info[:3])))'
    if ($LASTEXITCODE -ne 0 -or [version]$pythonVersion -lt [version]'3.11') {
        throw 'Install Python 3.11 or later.'
    }
    $nodeVersion = [version]((& node --version).TrimStart('v'))
    $supportedNode = ($nodeVersion.Major -eq 20 -and $nodeVersion.Minor -ge 19) -or
        ($nodeVersion.Major -eq 22 -and $nodeVersion.Minor -ge 12) -or $nodeVersion.Major -ge 24
    if (-not $supportedNode) { throw 'Use Node.js 20.19, 22.12, or a later supported release.' }
    # Use the native Windows launcher without invoking a command shell.
    $npm = (Get-Command $(if ($IsWindows) { 'npm.cmd' } else { 'npm' }) -CommandType Application).Source
    Write-Host "Using Python $pythonVersion and Node.js $nodeVersion."

    & $python -c 'import fastapi, pytest' 2>$null
    if ($LASTEXITCODE -ne 0) {
        & $python -m pip install -r (Join-Path $PSScriptRoot 'backend' 'requirements.txt') | Out-Host
        if ($LASTEXITCODE -ne 0) { throw 'Backend dependency installation failed.' }
    }
    if (-not (Test-Path (Join-Path $PSScriptRoot 'frontend' 'node_modules'))) {
        Push-Location (Join-Path $PSScriptRoot 'frontend')
        try {
            & $npm ci | Out-Host
            if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
        }
        finally { Pop-Location }
    }

    $env:CI = 'true'
    $backendSuccess = Run-Tests -Name 'Backend' -Directory (Join-Path $PSScriptRoot 'backend') -Action {
        & $python run_tests.py | Out-Host
        return $LASTEXITCODE -eq 0
    }
    $frontendSuccess = Run-Tests -Name 'Frontend' -Directory (Join-Path $PSScriptRoot 'frontend') -Action {
        & $npm test -- --watchAll=false --ci | Out-Host
        return $LASTEXITCODE -eq 0
    }
    if (-not ($backendSuccess -and $frontendSuccess)) { exit 1 }
    Write-Host 'All curated tests passed.'
}
catch {
    Write-Error $_
    exit 1
}
finally {
    if ($null -eq $previousCI) { Remove-Item Env:CI -ErrorAction SilentlyContinue }
    else { $env:CI = $previousCI }
    Pop-Location
}
