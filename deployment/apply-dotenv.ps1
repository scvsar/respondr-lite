[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$ResourceGroup,
    [Parameter(Mandatory)] [string]$FunctionAppName,
    [Parameter(Mandatory)] [string]$ContainerAppName,
    [string]$DotEnvPath = ".\.env.populated",

    # Keys treated as secrets in Container Apps (stored in CA secrets and referenced via secretref:)
    [string[]]$SecretKeys = @("AZURE_OPENAI_API_KEY", "AZURE_STORAGE_CONNECTION_STRING"),

    # Controls
    [switch]$OnlyFunction,
    [switch]$OnlyContainer,
    [switch]$NoSecretsInFunction,   # if set, do NOT write secret keys into Function App settings
    [switch]$DryRun,                # show what would change, but don't call az
    [switch]$VerboseLogging         # extra console output
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Log([string]$msg) {
    Write-Host ("[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $msg)
}
function Warn([string]$msg) { Write-Warning $msg }
function Err([string]$msg) { Write-Error $msg }

function HasKey($map, [string]$key) {
  if ($null -eq $map) { return $false }
  if ($map -is [System.Collections.IDictionary]) { return $map.Contains($key) } # OrderedDictionary
  if ($map -is [System.Collections.Generic.IDictionary[string,string]]) { return $map.ContainsKey($key) }
  return $false
}


if (-not (Test-Path $DotEnvPath)) { throw "DotEnv file not found: $DotEnvPath" }

# --- Parse .env into an ordered hashtable ---
$envMap = [ordered]@{}
$lineNum = 0
Get-Content -LiteralPath $DotEnvPath -Encoding UTF8 | ForEach-Object {
    $lineNum++
    $line = $_.Trim()
    if ($line -eq "" -or $line.StartsWith("#")) { return }

    # Parse KEY=VALUE (single =; allow = inside value)
    $idx = $line.IndexOf("=")
    if ($idx -lt 1) { Warn "Skipping line $lineNum (no KEY=VALUE): $line"; return }

    $key = $line.Substring(0, $idx).Trim()
    $val = $line.Substring($idx + 1) # keep as-is (may include quotes, commas, etc.)
    # Do not strip quotes; apps expect them sometimes (e.g., comma-separated lists)
    if ([string]::IsNullOrWhiteSpace($key)) { Warn "Skipping line $lineNum (empty key): $line"; return }

    # In .env a value can be empty: KEY=
    $envMap[$key] = $val
}

if ($VerboseLogging) {
    Log "Parsed $($envMap.Count) keys from ${DotEnvPath}:"
    $envMap.Keys | ForEach-Object { Write-Host "  $_=$($envMap[$_])" }
}

# Helpers
function AzJson {
    param([Parameter(Mandatory)][string[]]$Args)
    if ($DryRun) { Write-Host "DRY-RUN az $($Args -join ' ')"; return $null }
    $out = az @Args -o json --only-show-errors 2>$null
    if ([string]::IsNullOrWhiteSpace($out)) { return $null }
    return $out | ConvertFrom-Json
}

# --- Apply to Function App ---
if (-not $OnlyContainer) {
    Log "Applying to Function App: $FunctionAppName (RG: $ResourceGroup)"

    # Build settings payload; optionally exclude secrets
    $funcSettings = @{}
    foreach ($k in $envMap.Keys) {
        if ($NoSecretsInFunction -and ($SecretKeys -contains $k)) { continue }
        $v = $envMap[$k]
        # Skip null; allow empty-string values (explicit clears)
        if ($null -ne $v) { $funcSettings[$k] = "$v" }
    }

    if ($funcSettings.Count -eq 0) {
        Warn "No Function App settings to apply."
    }
    else {
        $args = @(
            "functionapp", "config", "appsettings", "set",
            "-g", $ResourceGroup, "-n", $FunctionAppName, "--settings"
        )

        foreach ($k in $funcSettings.Keys) { $args += "$k=$($funcSettings[$k])" }
        if ($VerboseLogging) { Write-Host "az $($args -join ' ')" }
        AzJson $args | Out-Null
        Log "Function App settings applied: $($funcSettings.Count) keys"
    }
}

# --- Apply to Container App ---
if (-not $OnlyFunction) {
    Log "Applying to Container App: $ContainerAppName (RG: $ResourceGroup)"

    # 1) Update secrets for secret keys present in the .env
  
    $secretsToSet = @()
    foreach ($k in $SecretKeys) {
  if (HasKey $envMap $k -and $null -ne $envMap[$k]) {
    $secretsToSet += "$k=$($envMap[$k])"
  }
}
    if ($secretsToSet.Count -gt 0) {
        $args = @("containerapp", "secret", "set", "-g", $ResourceGroup, "-n", $ContainerAppName, "--secrets") + $secretsToSet
        if ($VerboseLogging) { Write-Host "az $($args -join ' ')" }
        AzJson $args | Out-Null
        Log "Container App secrets updated: $($secretsToSet.Count)"
    }
    else {
        Log "No Container App secrets to set."
    }

    # 2) Build env var pairs, use secretref: for secret keys
    $envPairs = @()
    foreach ($k in $envMap.Keys) {
        $v = $envMap[$k]
        if ($null -eq $v) { continue }
        if ($SecretKeys -contains $k) {
            $envPairs += "$k=secretref:$k"
        }
        else {
            $envPairs += "$k=$v"
        }
    }

    if ($envPairs.Count -eq 0) {
        Warn "No Container App env vars to apply."
    }
    else {
        # Chunk in groups of 20 to avoid arg length limits
        $chunkSize = 20
        for ($i = 0; $i -lt $envPairs.Count; $i += $chunkSize) {
            $chunk = $envPairs[$i..([Math]::Min($i + $chunkSize - 1, $envPairs.Count - 1))]
            $args = @("containerapp", "update", "-g", $ResourceGroup, "-n", $ContainerAppName, "--set-env-vars") + $chunk
            if ($VerboseLogging) { Write-Host "az $($args -join ' ')" }
            AzJson $args | Out-Null
        }
        Log "Container App env vars applied: $($envPairs.Count) keys"
    }
}

Log "Done."
