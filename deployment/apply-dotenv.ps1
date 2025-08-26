[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$ResourceGroup,
    [string]$FunctionAppName,        # Now optional - will auto-discover if not provided
    [string]$ContainerAppName,       # Now optional - will auto-discover if not provided
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
    if ($map -is [System.Collections.Generic.IDictionary[string, string]]) { return $map.ContainsKey($key) }
    return $false
}

# Helpers
function AzJson {
    param(
        [Parameter(Mandatory)][string[]]$Args,
        [int]$Retries = 3,
        [int]$SleepSec = 2
    )
    if ($DryRun) { Write-Host "DRY-RUN az $($Args -join ' ')"; return $null }
    
    $attempt = 0
    while ($attempt -lt $Retries) {
        $attempt++
        try {
            $final = @() + $Args + @("--only-show-errors", "-o", "json")
            if ($VerboseLogging) { Write-Host "az $($final -join ' ')" }
            $json = & az @final 2>$null
            if ([string]::IsNullOrWhiteSpace($json)) { return $null }
            $obj = $json | ConvertFrom-Json -ErrorAction Stop
            if ($VerboseLogging) { Write-Host "→ Parsed JSON ok ($([Text.Encoding]::UTF8.GetByteCount($json)) bytes)" }
            return $obj
        }
        catch {
            Warn "az call failed (attempt $attempt/$Retries): $($_.Exception.Message)"
            if ($attempt -lt $Retries) { Start-Sleep -s $SleepSec } else { throw }
        }
    }
}

# --- Auto-discover resources if not provided ---
Log "Discovering resources in resource group: $ResourceGroup"

# Function App discovery
if (-not $FunctionAppName) {
    Log "Auto-discovering Function App..."
    $faList = AzJson @("functionapp", "list", "-g", $ResourceGroup)
    if (($faList | Measure-Object).Count -eq 1) {
        $FunctionAppName = $faList[0].name
        Log "Found Function App: $FunctionAppName"
    }
    elseif (($faList | Measure-Object).Count -gt 1) {
        $FunctionAppName = ($faList | Select-Object -ExpandProperty name | Sort-Object | Select-Object -First 1)
        Warn "Multiple Function Apps found; picking '$FunctionAppName'. Pass -FunctionAppName to override."
    }
    else { 
        if (-not $OnlyContainer) {
            throw "No Function Apps found in resource group '$ResourceGroup'."
        }
        else {
            Warn "No Function Apps found in '$ResourceGroup' (OnlyContainer mode - continuing)"
        }
    }
}

# Container App discovery
if (-not $ContainerAppName) {
    Log "Auto-discovering Container App..."
    $caList = AzJson @("containerapp", "list", "-g", $ResourceGroup)
    if (($caList | Measure-Object).Count -eq 1) {
        $ContainerAppName = $caList[0].name
        Log "Found Container App: $ContainerAppName"
    }
    elseif (($caList | Measure-Object).Count -gt 1) {
        $ContainerAppName = ($caList | Select-Object -ExpandProperty name | Sort-Object | Select-Object -First 1)
        Warn "Multiple Container Apps found; picking '$ContainerAppName'. Pass -ContainerAppName to override."
    }
    else { 
        if (-not $OnlyFunction) {
            Warn "No Container Apps found in '$ResourceGroup'"
            $ContainerAppName = $null
        }
        else {
            Log "No Container Apps found in '$ResourceGroup' (OnlyFunction mode - continuing)"
        }
    }
}

# Validate we have what we need based on the mode
if (-not $OnlyContainer -and -not $FunctionAppName) {
    throw "Function App name is required but could not be auto-discovered"
}
if (-not $OnlyFunction -and -not $ContainerAppName) {
    if ($OnlyContainer) {
        throw "Container App name is required but could not be auto-discovered"
    }
    else {
        Warn "No Container App found - will only apply to Function App"
        $OnlyFunction = $true
    }
}

# --- Parse .env file ---
if (-not (Test-Path $DotEnvPath)) { throw "DotEnv file not found: $DotEnvPath" }

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

# --- Apply to Function App ---
if (-not $OnlyContainer -and $FunctionAppName) {
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
if (-not $OnlyFunction -and $ContainerAppName) {
    Log "Applying to Container App: $ContainerAppName (RG: $ResourceGroup)"

    # Previously secrets were stored as Container App secrets and referenced via secretref.
    # Change: write secret values directly as container environment variables instead.
    Log "Embedding secret keys as container environment variables (not as secretrefs)"

    # 2) Get the container name using smarter selection logic
    $currentCA = AzJson @("containerapp", "show", "-g", $ResourceGroup, "-n", $ContainerAppName)
    $containerName = $null
    
    if ($currentCA -and $currentCA.properties.template.containers) {
        $containers = $currentCA.properties.template.containers
        
        # Prefer container whose name matches the app name (common pattern), else use first
        $containerName = ($containers | Where-Object { $_.name -eq $ContainerAppName } |
            Select-Object -ExpandProperty name -First 1)
        if (-not $containerName) { 
            $containerName = $containers[0].name 
        }
        
        Log "Found container name: $containerName (from $($containers.Count) total containers)"
    }
    else {
        throw "Could not determine container name for $ContainerAppName"
    }
}

# 3) Build env pairs ONLY from the .env file (let --set-env-vars merge, don't pre-merge)
$envPairsToSet = @()
foreach ($k in $envMap.Keys) {
    $v = $envMap[$k]
    if ($null -eq $v) { continue }

    if ($SecretKeys -contains $k) {
        # embed the secret value directly as an env var on the container app
        $envPairsToSet += "$k=$v"
    }
    else {
        # Do NOT escape quotes here; each pair is a single argument token
        $envPairsToSet += "$k=$v"
    }
}

if ($envPairsToSet.Count -gt 0) {
    $args = @(
        "containerapp", "update",
        "-g", $ResourceGroup,
        "-n", $ContainerAppName,
        "--container-name", $containerName,
        "--set-env-vars"           # safer than --replace-env-vars
    ) + $envPairsToSet

    if ($envPairsToSet.Count -gt 0) {
        Log "Container App env vars to set: $($envPairsToSet.Count)"
        
        # Try setting variables in smaller batches to avoid command line length limits
        $batchSize = 5
        $totalBatches = [Math]::Ceiling($envPairsToSet.Count / $batchSize)
        $successCount = 0
        
        for ($batchNum = 0; $batchNum -lt $totalBatches; $batchNum++) {
            $startIdx = $batchNum * $batchSize
            $endIdx = [Math]::Min($startIdx + $batchSize - 1, $envPairsToSet.Count - 1)
            $batch = $envPairsToSet[$startIdx..$endIdx]
            
            Log "Setting batch $($batchNum + 1)/$totalBatches ($($batch.Count) variables)"
            
            $args = @(
                "containerapp", "update",
                "-g", $ResourceGroup,
                "-n", $ContainerAppName,
                "--container-name", $containerName,
                "--set-env-vars"
            ) + $batch

            if ($VerboseLogging) {
                Log "Batch command: az $($args -join ' ')"
            }
            
            try {
                $result = AzJson $args
                $successCount += $batch.Count
                Log "Batch $($batchNum + 1) completed successfully"
                
                # Small delay between batches to avoid rate limiting
                if ($batchNum -lt $totalBatches - 1) {
                    Start-Sleep -Seconds 2
                }
            }
            catch {
                Err "Batch $($batchNum + 1) failed: $($_.Exception.Message)"
                Log "Failed variables in this batch:"
                $batch | ForEach-Object { Write-Host "  $_" }
            }
        }
        
        Log "Container App env vars set: $successCount/$($envPairsToSet.Count)"
    }
    else {
        Log "No Container App env vars to set."
    }
    
    # Add immediate verification after the update
    Log "Verifying environment variables were applied..."
    Start-Sleep -Seconds 5  # Give Azure time to process the update
    
    try {
        $verificationCA = AzJson @("containerapp", "show", "-g", $ResourceGroup, "-n", $ContainerAppName)
        
        # Find the specific container we updated by name (not just containers[0])
        $targetContainer = $null
        if ($verificationCA -and $verificationCA.properties.template.containers) {
            $targetContainer = $verificationCA.properties.template.containers | 
            Where-Object { $_.name -eq $containerName } | 
            Select-Object -First 1
        }
            
        if ($targetContainer) {
            Log "Verification: Checking container '$($targetContainer.name)'"
            if ($targetContainer.env) {
                $actualEnvCount = $targetContainer.env.Count
                Log "Verification: Target container now has $actualEnvCount environment variables"
                
                # List all env vars on the target container for debugging using safe property access
                Log "Environment variables on target container '$containerName':"
                $targetContainer.env | ForEach-Object {
                    $displayValue = if ($_.PSObject.Properties['secretRef'] -and $_.secretRef) { 
                        "secretref:$($_.secretRef)" 
                    }
                    elseif ($_.PSObject.Properties['value']) { 
                        $_.value 
                    }
                    else { 
                        "(unknown structure)" 
                    }
                    Write-Host "  $($_.name) = $displayValue"
                }
                
                if ($actualEnvCount -lt $successCount + 4) {
                    # 4 is the baseline we saw
                    Warn "Environment variables may not have been applied correctly"
                    Log "Expected at least $($successCount + 4), found $actualEnvCount"
                }
            }
            else {
                Warn "Target container '$containerName' has no environment variables"
            }
        }
        else {
            Err "Could not find target container '$containerName' in verification"
            # Show all available containers for debugging
            Log "Available containers:"
            $verificationCA.properties.template.containers | ForEach-Object {
                Write-Host "  $($_.name)"
            }
        }
        
        # Check revision status since env var changes create new revisions
        Log "Checking Container App revisions..."
        $revisions = AzJson @("containerapp", "revision", "list", "-g", $ResourceGroup, "-n", $ContainerAppName, "--query", "[].{name:name, active:properties.active, traffic:properties.trafficWeight}")
        if ($revisions) {
            Log "Current revisions:"
            $revisions | ForEach-Object { 
                $status = if ($_.active) { "active" } else { "inactive" }
                Write-Host "  $($_.name): $status, traffic=$($_.traffic)%" 
            }
        }
    }
    catch {
        Warn "Verification check failed: $($_.Exception.Message)"
    }
}

# --- Verification: List current settings/secrets ---
Log ""
Log "=== VERIFICATION: Current App Settings ==="

if (-not $OnlyContainer -and $FunctionAppName) {
    Log "Function App '$FunctionAppName' settings:"
    try {
        $currentFuncSettings = AzJson @("functionapp", "config", "appsettings", "list", "-g", $ResourceGroup, "-n", $FunctionAppName)
        if ($currentFuncSettings) {
            $sortedSettings = $currentFuncSettings | Sort-Object { $_.name }
            foreach ($setting in $sortedSettings) {
                $displayValue = $setting.value
                # Mask sensitive values for display
                if ($SecretKeys -contains $setting.name -or 
                    $setting.name -match "(?i)(SECRET|TOKEN|PASSWORD|APIKEY|API_KEY|CONNSTR|CONNECTION|SAS|PRIVATE|CERT|PWD|KEY)") {
                    $displayValue = "*" * [Math]::Min(8, $setting.value.Length) + " (masked)"
                }
                Write-Host "  $($setting.name) = $displayValue"
            }
            Log "Function App total settings: $($currentFuncSettings.Count)"
        }
        else {
            Warn "Could not retrieve Function App settings"
        }
    }
    catch {
        Warn "Failed to retrieve Function App settings: $($_.Exception.Message)"
    }
    Log ""
}

if (-not $OnlyFunction -and $ContainerAppName) {
    Log "Container App '$ContainerAppName' environment variables and secrets:"
    try {
        $currentCA = AzJson @("containerapp", "show", "-g", $ResourceGroup, "-n", $ContainerAppName)
        if ($currentCA -and $currentCA.properties.template.containers) {
            $container = $currentCA.properties.template.containers[0]
            
            # Show environment variables
            if ($container.env) {
                $sortedEnv = $container.env | Sort-Object { $_.name }
                foreach ($envVar in $sortedEnv) {
                    $displayValue = ""
                    
                    # Check for secretRef property (case-sensitive check)
                    if ($envVar.PSObject.Properties['secretRef'] -and $envVar.secretRef) {
                        $displayValue = "secretref:$($envVar.secretRef)"
                    }
                    elseif ($envVar.PSObject.Properties['value']) {
                        $rawValue = $envVar.value
                        # Mask sensitive values that aren't using secretRef
                        if ($SecretKeys -contains $envVar.name -or 
                            $envVar.name -match "(?i)(SECRET|TOKEN|PASSWORD|APIKEY|API_KEY|CONNSTR|CONNECTION|SAS|PRIVATE|CERT|PWD|KEY)") {
                            $displayValue = "*" * [Math]::Min(8, $rawValue.Length) + " (masked)"
                        }
                        else {
                            $displayValue = $rawValue
                        }
                    }
                    else {
                        # Handle other possible structures
                        $displayValue = "(structure unknown)"
                    }
                    
                    Write-Host "  $($envVar.name) = $displayValue"
                }
                Log "Container App total env vars: $($container.env.Count)"
            }
            
            # Show available secrets (names only for security)
            if ($currentCA.properties.configuration.secrets) {
                $secretNames = $currentCA.properties.configuration.secrets | Select-Object -ExpandProperty name
                Log "Container App secrets available: $($secretNames -join ', ')"
            }
        }
        else {
            Warn "Could not retrieve Container App configuration"
        }
    }
    catch {
        Warn "Failed to retrieve Container App configuration: $($_.Exception.Message)"
    }
    Log ""
}

# Show comparison with what was in the .env file
Log "=== COMPARISON: .env vs Applied Settings ==="
$appliedCount = 0
$missingCount = 0
$missingKeys = @()

foreach ($key in $envMap.Keys) {
    $foundInFunc = $false
    $foundInCA = $false
    
    # Check Function App (if applicable)
    if (-not $OnlyContainer -and $FunctionAppName -and $currentFuncSettings) {
        $funcSetting = $currentFuncSettings | Where-Object { $_.name -eq $key }
        if ($funcSetting) {
            $foundInFunc = $true
            if ($NoSecretsInFunction -and ($SecretKeys -contains $key)) {
                # This is expected - we skipped secrets
            }
        }
    }
    
    # Check Container App (if applicable)  
    if (-not $OnlyFunction -and $ContainerAppName -and $currentCA -and $currentCA.properties.template.containers) {
        $container = $currentCA.properties.template.containers[0]
        if ($container.env) {
            $caEnv = $container.env | Where-Object { $_.name -eq $key }
            if ($caEnv) {
                $foundInCA = $true
            }
        }
    }
    
    # Determine if this key was expected to be applied
    $shouldBeInFunc = (-not $OnlyContainer -and $FunctionAppName -and -not ($NoSecretsInFunction -and ($SecretKeys -contains $key)))
    $shouldBeInCA = (-not $OnlyFunction -and $ContainerAppName)
    
    if (($shouldBeInFunc -and $foundInFunc) -or ($shouldBeInCA -and $foundInCA) -or (-not $shouldBeInFunc -and -not $shouldBeInCA)) {
        $appliedCount++
    }
    else {
        $missingCount++
        $missingKeys += $key
    }
}

Log "Applied successfully: $appliedCount/$($envMap.Keys.Count) keys"
if ($missingCount -gt 0) {
    Warn "Missing or not applied: $missingCount keys: $($missingKeys -join ', ')"
}
else {
    Log "All keys from .env file were successfully applied!"
}

Log "Done."