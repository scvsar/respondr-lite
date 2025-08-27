<# 
.SYNOPSIS
  Generate a .env.populated from live Azure resources; optionally apply to Function App & Container App.

.NOTES
  - Adds detailed step logging, timings, and retries for az calls.
  - Use -Verbose to see executed az commands and parsed payload sizes.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$ResourceGroup,
    [string]$StorageAccountName,
    [string]$FunctionAppName,
    [string]$OpenAiName,
    [string]$ContainerAppName,
    [string]$OutputPath = ".\.env.populated",
    [switch]$Apply,
    # ---------- Optional overrides for non-dynamic keys ----------
    [string]$ALLOWED_EMAIL_DOMAINS,
    [string]$ALLOWED_ADMIN_USERS,
    [string]$WEBHOOK_API_KEY,
    [string]$BACKEND_API_KEY,
    [string]$ALLOWED_GROUPME_GROUP_IDS,
    [string]$AZURE_OPENAI_API_VERSION,
    [string]$TIMEZONE,
    [string]$DEBUG_FULL_LLM_LOG,
    [string]$RETENTION_DAYS,
    [string]$DEFAULT_MAX_COMPLETION_TOKENS,
    [string]$MIN_COMPLETION_TOKENS,
    [string]$MAX_COMPLETION_TOKENS_CAP,
    [string]$LLM_MAX_RETRIES,
    [string]$LLM_TOKEN_INCREASE_FACTOR,
    [string]$DebugFlag,              
    [string]$ALLOW_LOCAL_AUTH_BYPASS,
    [string]$LOCAL_BYPASS_IS_ADMIN,
    [string]$ALLOW_CLEAR_ALL,
    [string]$STORAGE_TABLE_NAME,
    [string]$STORAGE_QUEUE_NAME,
    [string]$ENABLE_LOCAL_AUTH
)



Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ---------- Logging helpers ----------
$script:StepIndex = 0
$swGlobal = [System.Diagnostics.Stopwatch]::StartNew()

function Now { Get-Date -Format "HH:mm:ss.fff" }

function Log([string]$msg) {
    Write-Host ("[{0}] {1}" -f (Now), $msg)
}

function Warn([string]$msg) {
    Write-Warning ("[{0}] {1}" -f (Now), $msg)
}

function Err([string]$msg) {
    Write-Error ("[{0}] {1}" -f (Now), $msg)
}

function Start-Step([string]$name) {
    $script:StepIndex++
    $script:curr = @{
        Name      = $name
        Stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    }
    Write-Progress -Id 1 -Activity "Generating .env" -Status $name -PercentComplete (($StepIndex * 10) % 100)
    Log ("▶ Step {0}: {1}" -f $StepIndex, $name)
}

function End-Step {
    if ($script:curr) {
        $script:curr.Stopwatch.Stop()
        Log ("✓ Step {0} done in {1:n2}s" -f $StepIndex, ($script:curr.Stopwatch.Elapsed.TotalSeconds))
        $script:curr = $null
    }
}

function _pick([string]$override, [string]$default) {
    if ($override -ne $null -and $override -ne "") { return $override }
    return $default
}


# ---------- Robust az wrapper with retries ----------
function AzJson {
    param(
        [Parameter(Mandatory)][string[]]$Args,
        [int]$Retries = 3,
        [int]$SleepSec = 2
    )
    $attempt = 0
    while ($attempt -lt $Retries) {
        $attempt++
        try {
            $final = @() + $Args + @("--only-show-errors", "-o", "json")
            Write-Verbose ("az {0}" -f ($final -join ' '))
            $json = & az @final 2>$null
            if ([string]::IsNullOrWhiteSpace($json)) { return $null }
            $obj = $json | ConvertFrom-Json -ErrorAction Stop
            Write-Verbose ("→ Parsed JSON ok ({0:n0} bytes)" -f ([Text.Encoding]::UTF8.GetByteCount($json)))
            return $obj
        }
        catch {
            Warn ("az call failed (attempt {0}/{1}): {2}" -f $attempt, $Retries, $_.Exception.Message)
            if ($attempt -lt $Retries) { Start-Sleep -s $SleepSec } else { throw }
        }
    }
}

function AzTsv {
    param(
        [Parameter(Mandatory)][string[]]$Args,
        [int]$Retries = 3,
        [int]$SleepSec = 2
    )
    $attempt = 0
    while ($attempt -lt $Retries) {
        $attempt++
        try {
            $final = @() + $Args + @("--only-show-errors", "-o", "tsv")
            Write-Verbose ("az {0}" -f ($final -join ' '))
            $out = & az @final 2>$null
            if ($LASTEXITCODE -ne 0) { throw "az exited with code $LASTEXITCODE" }
            Write-Verbose ("→ TSV ok (len={0})" -f ($out.Length))
            return $out
        }
        catch {
            Warn ("az call failed (attempt {0}/{1}): {2}" -f $attempt, $Retries, $_.Exception.Message)
            if ($attempt -lt $Retries) { Start-Sleep -s $SleepSec } else { throw }
        }
    }
}

Start-Step "Discover resource names in RG (when not provided)"

# Function App
if (-not $FunctionAppName) {
  $faList = AzJson @("functionapp","list","-g",$ResourceGroup)
  if (($faList | Measure-Object).Count -eq 1) {
    $FunctionAppName = $faList[0].name
  } elseif (($faList | Measure-Object).Count -gt 1) {
    $FunctionAppName = ($faList | Select-Object -ExpandProperty name | Sort-Object | Select-Object -First 1)
    Warn "Multiple Function Apps found; picking '$FunctionAppName'. Pass -FunctionAppName to override."
  } else { throw "No Function Apps found in resource group '$ResourceGroup'." }
  Log "Function App: $FunctionAppName"
}

# Container App
if (-not $ContainerAppName) {
  $caList = AzJson @("containerapp","list","-g",$ResourceGroup)
  if (($caList | Measure-Object).Count -eq 1) {
    $ContainerAppName = $caList[0].name
  } elseif (($caList | Measure-Object).Count -gt 1) {
    $ContainerAppName = ($caList | Select-Object -ExpandProperty name | Sort-Object | Select-Object -First 1)
    Warn "Multiple Container Apps found; picking '$ContainerAppName'. Pass -ContainerAppName to override."
  } else { Warn "No Container Apps found in '$ResourceGroup'."; $ContainerAppName = $null }
  if ($ContainerAppName) { Log "Container App: $ContainerAppName" }
}

# AOAI account (Cognitive Services kind == OpenAI)
if (-not $OpenAiName) {
  $aoaiList = AzJson @("cognitiveservices","account","list","-g",$ResourceGroup,"--query","[?kind=='OpenAI']")
  if (($aoaiList | Measure-Object).Count -eq 1) {
    $OpenAiName = $aoaiList[0].name
  } elseif (($aoaiList | Measure-Object).Count -gt 1) {
    $OpenAiName = ($aoaiList | Select-Object -ExpandProperty name | Sort-Object | Select-Object -First 1)
    Warn "Multiple AOAI accounts found; picking '$OpenAiName'. Pass -OpenAiName to override."
  } else { throw "No Azure OpenAI (kind='OpenAI') accounts found in '$ResourceGroup'." }
  Log "AOAI: $OpenAiName"
}

# Storage Account — prefer the one referenced by the Function App's AzureWebJobsStorage
if (-not $StorageAccountName) {
  $faSettings = AzJson @("functionapp","config","appsettings","list","-g",$ResourceGroup,"-n",$FunctionAppName)
  $webJobs = $faSettings | Where-Object { $_.name -eq "AzureWebJobsStorage" }
  if ($webJobs -and $webJobs.value -match "AccountName=([^;]+)") {
    $StorageAccountName = $matches[1]
    Log "Storage (from AzureWebJobsStorage): $StorageAccountName"
  }
  if (-not $StorageAccountName) {
    $saList = AzJson @("storage","account","list","-g",$ResourceGroup)
    if (($saList | Measure-Object).Count -eq 1) {
      $StorageAccountName = $saList[0].name
    } elseif (($saList | Measure-Object).Count -gt 1) {
      $StorageAccountName = ($saList | Select-Object -ExpandProperty name | Sort-Object | Select-Object -First 1)
      Warn "Multiple Storage Accounts found; picking '$StorageAccountName'. Pass -StorageAccountName to override."
    } else { throw "No Storage Accounts found in '$ResourceGroup'." }
    Log "Storage (by list): $StorageAccountName"
  }
}
End-Step


Start-Step "Collect: Storage account"
$storage = AzJson @("storage", "account", "show", "-g", $ResourceGroup, "-n", $StorageAccountName)
if (-not $storage) { Err "Storage account '$StorageAccountName' not found"; throw }
End-Step

Start-Step "Collect: Storage connection string and key"
$storageConn = AzTsv @("storage", "account", "show-connection-string", "-g", $ResourceGroup, "-n", $StorageAccountName)
$storageKeys = AzJson @("storage", "account", "keys", "list", "-g", $ResourceGroup, "-n", $StorageAccountName)
if (-not $storageKeys -or -not $storageKeys[0].value) { throw "No storage keys returned for $StorageAccountName" }
$storageKey1 = $storageKeys[0].value
End-Step


Start-Step "Discover: Tables and Queues"
# names only (robust against preview warnings)
$tableNames = AzTsv @("storage", "table", "list", "--account-name", $StorageAccountName, "--account-key", $storageKey1, "--query", "[].name")
$queueNames = AzTsv @("storage", "queue", "list", "--account-name", $StorageAccountName, "--account-key", $storageKey1, "--query", "[].name")

# Rebuild objects with a .name prop so the rest of the script stays unchanged
$tableList = @()
$queueList = @()
if ($tableNames) { $tableList = ($tableNames -split "`r?`n" | Where-Object { $_ }) | ForEach-Object { [pscustomobject]@{ name = $_ } } }
if ($queueNames) { $queueList = ($queueNames -split "`r?`n" | Where-Object { $_ }) | ForEach-Object { [pscustomobject]@{ name = $_ } } }

function Pick-Name($items, $prop, $fallbacks) {
    if ($items -and $items.Count -eq 1) { return $items[0].$prop }
    foreach ($f in $fallbacks) {
        if ($items | Where-Object { $_.$prop -eq $f }) { return $f }
    }
    return ""
}
$storageTableName = Pick-Name $tableList "name" @("ResponderMessages", "RespondrMessages")
$storageQueueName = Pick-Name $queueList "name" @("respondr-incoming", "RespondrIncoming")
Log ("Tables found: {0}; Queues found: {1}" -f ($tableList.Count), ($queueList.Count))
End-Step


Start-Step "Collect: Function App and app settings"
$func = AzJson @("functionapp", "show", "-g", $ResourceGroup, "-n", $FunctionAppName)
if (-not $func) { Err "Function App '$FunctionAppName' not found"; throw }
$funcAppSettings = AzJson @("functionapp","config","appsettings","list","-g",$ResourceGroup,"-n",$FunctionAppName)
if ($funcAppSettings) {
    $qSetting = $funcAppSettings | Where-Object { $_.name -eq "STORAGE_QUEUE_NAME" }
    if ($qSetting -and $qSetting.value) { 
        Log "Using STORAGE_QUEUE_NAME from Function App settings"
        $storageQueueName = $qSetting.value 
    }
}
End-Step

Start-Step "Collect: Azure OpenAI account, endpoint, keys, deployments"
$aoai = AzJson @("cognitiveservices", "account", "show", "-g", $ResourceGroup, "-n", $OpenAiName)
if (-not $aoai) { Err "AOAI account '$OpenAiName' not found"; throw }
$aoaiEndpoint = $aoai.properties.endpoint

$aoaiKeys = AzJson @("cognitiveservices", "account", "keys", "list", "-g", $ResourceGroup, "-n", $OpenAiName)
$aoaiKey = $aoaiKeys.key1

# Get deployment names via JMESPath, return as TSV lines
$namesTsv = AzTsv @(
    "cognitiveservices", "account", "deployment", "list",
    "-g", $ResourceGroup, "-n", $OpenAiName,
    "--query", "[].name"
)

# Normalize to an array, even if only one name comes back
$deploymentNames = @()
if ($namesTsv) {
    $deploymentNames = @($namesTsv -split "`r?`n" | Where-Object { $_ })
}

$aoaiDeploymentName = $null
if (@($deploymentNames).Count -gt 0) {
    $aoaiDeploymentName = ($deploymentNames | Select-Object -First 1)
    Log "AOAI deployments found: $($deploymentNames -join ', ')"
    Log "Selected AOAI deployment: $aoaiDeploymentName"
}
else {
    Warn "No AOAI deployments found in this account."
}

End-Step



Start-Step "Collect: Container App details"
$ca = AzJson @("containerapp", "show", "-g", $ResourceGroup, "-n", $ContainerAppName)
if (-not $ca) { Err "Container App '$ContainerAppName' not found"; throw }
$containerFqdn = $ca.properties.configuration.ingress.fqdn
$containerTargetPort = $ca.properties.configuration.ingress.targetPort
End-Step

Start-Step "Generate .env file"
$samplePath = ".\.env.sample"
$lines = @()
if (Test-Path $samplePath) {
    $raw = Get-Content $samplePath -Raw -Encoding UTF8
    $lines = $raw -split "`r?`n"
}

# ---------- Build the kv map for .env ----------
$kv = [ordered]@{
  # Common
  "ALLOWED_EMAIL_DOMAINS"           = _pick $ALLOWED_EMAIL_DOMAINS "example.com,example.org"
  "ALLOWED_ADMIN_USERS"             = _pick $ALLOWED_ADMIN_USERS   '"bob@example.com,alice@example.com"'

  # Security
  "WEBHOOK_API_KEY"                 = _pick $WEBHOOK_API_KEY                ""
  "BACKEND_API_KEY"                 = _pick $BACKEND_API_KEY                ""
  "ALLOWED_GROUPME_GROUP_IDS"       = _pick $ALLOWED_GROUPME_GROUP_IDS      ""

  # LLM / Azure OpenAI (dynamic where possible)
  "AZURE_OPENAI_API_KEY"            = $aoaiKey
  "AZURE_OPENAI_ENDPOINT"           = $aoaiEndpoint
  "AZURE_OPENAI_DEPLOYMENT"         = $aoaiDeploymentName
  "AZURE_OPENAI_API_VERSION"        = _pick $AZURE_OPENAI_API_VERSION "2024-12-01-preview"

  # App behavior
  "TIMEZONE"                        = _pick $TIMEZONE           "America/Los_Angeles"
  "DEBUG_FULL_LLM_LOG"              = _pick $DEBUG_FULL_LLM_LOG "false"
  "RETENTION_DAYS"                  = _pick $RETENTION_DAYS     "30"

  # LLM tuning / limits
  "DEFAULT_MAX_COMPLETION_TOKENS"   = _pick $DEFAULT_MAX_COMPLETION_TOKENS "4096"
  "MIN_COMPLETION_TOKENS"           = _pick $MIN_COMPLETION_TOKENS         "2048"
  "MAX_COMPLETION_TOKENS_CAP"       = _pick $MAX_COMPLETION_TOKENS_CAP     "16384"
  "LLM_MAX_RETRIES"                 = _pick $LLM_MAX_RETRIES               "3"
  "LLM_TOKEN_INCREASE_FACTOR"       = _pick $LLM_TOKEN_INCREASE_FACTOR     "1.5"

  # Debug / local dev flags
  "DEBUG"                           = _pick $DebugFlag               "false"
  "ALLOW_LOCAL_AUTH_BYPASS"         = _pick $ALLOW_LOCAL_AUTH_BYPASS "true"
  "LOCAL_BYPASS_IS_ADMIN"           = _pick $LOCAL_BYPASS_IS_ADMIN   "true"
  "ALLOW_CLEAR_ALL"                 = _pick $ALLOW_CLEAR_ALL         "true"

  # Storage (dynamic, but overridable)
  "AZURE_STORAGE_CONNECTION_STRING" = $storageConn
  "AZURE_STORAGE_ACCOUNT"           = $StorageAccountName
  "STORAGE_TABLE_NAME"              = _pick $STORAGE_TABLE_NAME $storageTableName
  "STORAGE_QUEUE_NAME"              = _pick $STORAGE_QUEUE_NAME $storageQueueName
  
  # Authentication
  "ENABLE_LOCAL_AUTH"               = _pick $ENABLE_LOCAL_AUTH "true"
  
  # Deployment tracking (auto-generated)
  "REDEPLOY_AT"                     = (Get-Date -Format "yyyyMMdd-HHmmss")
}



function Upsert-Line($existingLines, $key, $value) {
    $pattern = "^\s*($([regex]::Escape($key)))\s*="
    $match = $existingLines | Select-String -Pattern $pattern -CaseSensitive
    if ($match) {
        $idx = $match.LineNumber - 1
        $existingLines[$idx] = "$key=$value"
    }
    else {
        $existingLines += "$key=$value"
    }
    return $existingLines
}

if ($lines.Count -gt 0) {
    foreach ($k in $kv.Keys) {
        if (-not [string]::IsNullOrEmpty($kv[$k])) {
            $lines = Upsert-Line $lines $k $kv[$k]
        }
        else {
            Warn ("No value for {0}; leaving sample/default as-is" -f $k)
        }
    }
    Set-Content -Path $OutputPath -Value ($lines -join "`r`n") -NoNewline -Encoding UTF8
}
else {
    $out = @("# Generated $(Get-Date -Format s)")
    foreach ($k in $kv.Keys) { if ($kv[$k]) { $out += "$k=$($kv[$k])" } }
    $out += "TIMEZONE=America/Los_Angeles"
    $out += "DEBUG=false"
    Set-Content -Path $OutputPath -Value ($out -join "`r`n") -NoNewline -Encoding UTF8
}
Log ("Wrote {0}" -f $OutputPath)
End-Step

if ($Apply) {
    Start-Step "Apply: Function App settings & Container App env"

    # 1) Secrets first (AOAI key + Storage conn string)
    AzJson @(
        "containerapp", "secret", "set",
        "-g", $ResourceGroup, "-n", $ContainerAppName,
        "--secrets",
        "AZURE_OPENAI_API_KEY=$aoaiKey",
        "AZURE_STORAGE_CONNECTION_STRING=$storageConn"
    ) | Out-Null

    # 2) Build a hashtable of ALL settings from $kv for the Function App
    #    (Function App can store secrets in settings; you already have WEBSITE_RUN_FROM_PACKAGE etc.)
    $funcSettings = @{}
    foreach ($k in $kv.Keys) {
        $v = $kv[$k]
        if ($null -ne $v -and $v -ne "") { $funcSettings[$k] = "$v" }
    }

    # Function App update (bulk)
    $faArgs = @("functionapp","config","appsettings","set","-g",$ResourceGroup,"-n",$FunctionAppName,"--settings")
    foreach ($k in $funcSettings.Keys) { $faArgs += "$k=$($funcSettings[$k])" }
    AzJson @faArgs | Out-Null

    # 3) Container App env: use secretref for the two sensitive ones; plain env for the rest
    $envPairs = @()
    foreach ($k in $kv.Keys) {
        $v = $kv[$k]
        if ($null -eq $v -or $v -eq "") { continue }
        switch ($k) {
            "AZURE_OPENAI_API_KEY" { $envPairs += "$k=secretref:AZURE_OPENAI_API_KEY" }
            "AZURE_STORAGE_CONNECTION_STRING" { $envPairs += "$k=secretref:AZURE_STORAGE_CONNECTION_STRING" }
            default { $envPairs += "$k=$v" }
        }
    }

    # Split to avoid command-line too long (rare, but safe)
    AzJson @(
        "containerapp", "update",
        "-g", $ResourceGroup, "-n", $ContainerAppName,
        "--set-env-vars"
        + $envPairs
    ) | Out-Null

    End-Step

}

# ---------- Summary ----------
Write-Progress -Id 1 -Activity "Generating .env" -Completed
Log ""
Log "Summary:"
Log ("  Storage Conn : (redacted) length {0}" -f ($storageConn.Length))
Log ("  Table Name   : {0}" -f $storageTableName)
Log ("  Queue Name   : {0}" -f $storageQueueName)
Log ("  AOAI Endpoint: {0}" -f $aoaiEndpoint)
Log ("  AOAI Key     : (redacted) length {0}" -f ($aoaiKey.Length))
Log ("  AOAI Deploy  : {0}" -f $aoaiDeploymentName)
Log ("  Container URL: https://{0} (port {1})" -f $containerFqdn, $containerTargetPort)
Log ("Done in {0:n2}s" -f $swGlobal.Elapsed.TotalSeconds)
