#!/usr/bin/env pwsh
# Quick spot-check runner for the SAR benchmark using the backend venv
param(
  [string]$Models = "gpt-5-chat,gpt-5-nano",
  [switch]$AssistedOnly,
  [switch]$Raw,
  [int]$ToleranceMin = 2,
  [switch]$DebugIO,
  [string]$DebugDir
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$bench = $PSScriptRoot
$venv = Join-Path $backend '.venv'
$python = Join-Path $venv 'Scripts/python.exe'
if (!(Test-Path $python)) {
  Write-Warning "Backend venv python not found at $python. Falling back to 'python' in PATH (ensure the backend venv is activated)."
  $python = 'python'
}

# Load env from backend/.env and map to what benchmark expects
$backendEnv = Join-Path $backend '.env'
if (Test-Path $backendEnv) {
  Get-Content $backendEnv | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith('#')) { return }
    $idx = $line.IndexOf('=')
    if ($idx -gt 0) {
      $k = $line.Substring(0, $idx).Trim()
      $v = $line.Substring($idx+1).Trim()
      # Strip optional surrounding quotes
      if (($v.StartsWith('"') -and $v.EndsWith('"')) -or ($v.StartsWith("'") -and $v.EndsWith("'"))) { $v = $v.Substring(1, $v.Length-2) }
      Set-Item -Path "Env:$k" -Value $v -ErrorAction SilentlyContinue
    }
  }
}

# Map Azure env to benchmark-specific names
if ($env:AZURE_OPENAI_ENDPOINT) { $env:model_endpoint = $env:AZURE_OPENAI_ENDPOINT }
if ($env:AZURE_OPENAI_API_KEY) { $env:model_api_key = $env:AZURE_OPENAI_API_KEY }
if ($env:AZURE_OPENAI_API_VERSION) { $env:API_VERSION = $env:AZURE_OPENAI_API_VERSION }
if (-not $env:model_endpoint -or -not $env:model_api_key) { Write-Error "Azure OpenAI env not set. Ensure backend/.env has AZURE_OPENAI_* values." }
# Install benchmark extras in the same venv
Push-Location $bench
try {
  # Ensure pip is available and up to date
  try { & $python -m pip --version | Out-Null }
  catch { & $python -m ensurepip --upgrade | Out-Host }
  & $python -m pip install -U pip setuptools wheel | Out-Host
  & $python -m pip install -r requirements.txt | Out-Host
  $argvList = @()
  if ($AssistedOnly) { $argvList += "--comprehensive"; $argvList += "--assisted-only" } elseif ($Raw) { $argvList += "--raw" }
  if ($Models) { $argvList += "--models"; $argvList += $Models }
  $argvList += "--tolerance-min"; $argvList += $ToleranceMin
  if ($DebugIO) { $argvList += "--debug-io" }
  if ($DebugDir) { $argvList += "--debug-dir"; $argvList += $DebugDir }
  & $python .\sar_llm_extraction_benchmark.py @argvList
}
finally {
  Pop-Location
}
