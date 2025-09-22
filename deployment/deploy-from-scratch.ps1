# create the resource group if it doesn't exist using az cli
# expected Bicep params:
#param(
#    [Parameter(Mandatory = $true)] [string]$ResourceGroup,
#    [Parameter(Mandatory = $true)] [string]$StorageAccountName,
#    [Parameter(Mandatory = $true)] [string]$FunctionAppName,
#    [Parameter(Mandatory = $true)] [string]$Location,
#    [Parameter(Mandatory = $true)] [string]$OpenAiName,
#    [Parameter(Mandatory = $true)] [string]$OpenAiLocation
#)

function Get-ShortHash {
  param(
    [Parameter(Mandatory=$true)] [string]$Text,
    [int]$Length = 8
  )
  $bytes = [System.Text.Encoding]::UTF8.GetBytes($Text)
  $sha = [System.Security.Cryptography.SHA256]::Create()
  $hash = $sha.ComputeHash($bytes)
  $hex = ([System.BitConverter]::ToString($hash)).Replace('-','').ToLower()
  return $hex.Substring(0, [Math]::Min($Length, $hex.Length))
}


function New-UniqueHyphenName {
  param(
    [Parameter(Mandatory=$true)] [string]$BaseName,
    [string]$Salt = "",
    [int]$MaxLength = 64
  )
  # AOAI / many resources: 2-64 chars, lowercase letters/numbers/hyphens, no leading/trailing hyphen
  $clean = ($BaseName -replace '[^a-z0-9-]','').ToLower()
  $suffix = Get-ShortHash -Text "$BaseName|$Salt" -Length 8
  $candidate = "$clean-$suffix".Trim('-')
  if ($candidate.Length -gt $MaxLength) { $candidate = $candidate.Substring(0, $MaxLength).Trim('-') }
  if ($candidate.Length -lt 2) { $candidate = ($candidate + "-aa").Substring(0,[Math]::Min(2,$MaxLength)) }
  return $candidate
}

function New-UniqueStorageAccountName {
  param(
    [Parameter(Mandatory=$true)] [string]$BaseName,
    [string]$Salt = ""
  )
  # Storage account name rules: 3-24 chars, lowercase letters and numbers only
  $hashLength = 8
  $cleanBase = ($BaseName -replace '[^a-z0-9]','').ToLower()
  $saltInput = "$BaseName|$Salt"
  $shortHash = Get-ShortHash -Text $saltInput -Length $hashLength

  $maxTotal = 24
  $maxBaseLen = $maxTotal - $shortHash.Length
  if ($cleanBase.Length -gt $maxBaseLen) {
    $cleanBase = $cleanBase.Substring(0, $maxBaseLen)
  }

  $candidate = ($cleanBase + $shortHash).ToLower()

  # ensure min length of 3 (pad with 'sa' if necessary)
  while ($candidate.Length -lt 3) {
    $candidate += 'sa'
  }
  return $candidate.Substring(0, [Math]::Min($candidate.Length, $maxTotal))
}

# --- Logging helpers -----------------------------------------------------
$ErrorActionPreference = 'Stop'

function Log {
  param(
    [Parameter(Mandatory=$true)] [string]$Message
  )
  $ts = Get-Date -Format o
  $line = "[$ts] $Message"
  Write-Host $line
  try {
    if (-not $global:LogFile) {
      # place log next to this script
      if ($PSVersionTable.PSVersion.Major -ge 3 -and $PSScriptRoot) {
        $global:LogFile = Join-Path $PSScriptRoot 'deploy-from-scratch.log'
      }
      else {
        $global:LogFile = Join-Path (Get-Location) 'deploy-from-scratch.log'
      }
    }
    Add-Content -Path $global:LogFile -Value $line
  }
  catch {
    Write-Host "Failed to write to log file: $_" -ForegroundColor Yellow
  }
}
function Assert-Name($name, $pattern, $max) {
  if ($name.Length -gt $max -or -not ($name -match $pattern)) {
    throw "Name '$name' violates rules (max=$max, pattern=$pattern)"
  }
}
function Run-ProcessCapture {
  param(
    [Parameter(Mandatory=$true)] [string]$Exe,
    [Parameter(Mandatory=$false)] [string[]]$Args
  )
  $allArgs = $Args -join ' '
  Log "Running: $Exe $allArgs"
  try {
    $out = & $Exe @Args 2>&1
    $joined = if ($out -is [System.Array]) { $out -join "`n" } else { [string]$out }
    # Keep the original output for return/save, but sanitize what we write to the log
    $joinedOriginal = $joined

    function Sanitize-LogOutput([string]$text) {
      if ([string]::IsNullOrWhiteSpace($text)) { return $text }
      $lines = $text -split "`n"
      $keep = @()
      foreach ($l in $lines) {
        $trim = $l.TrimStart()
        # filter out lines that look like PowerShell source code (variable assignments, control keywords, param blocks, comments)
        if ($trim -match '^(\$[a-zA-Z_]|if\s*\(|for(each)?\s*\(|function\s+|param\s*\(|return\s|throw\s|class\s+|#)') {
          continue
        }
        $keep += $l
      }
      $result = ($keep -join "`n").Trim()
      if ([string]::IsNullOrWhiteSpace($result)) { return '<script-source-removed-or-empty-output>' }
      return $result
    }

    # Attempt to detect JSON output and pretty-print it for readability
    $joinedTrim = $joined.Trim()
    $outputToLog = $joined
    try {
      if ($joinedTrim.StartsWith('{') -or $joinedTrim.StartsWith('[')) {
        $parsed = $null
        try { $parsed = $joined | ConvertFrom-Json -ErrorAction Stop } catch { $parsed = $null }
        if ($null -ne $parsed) {
          $outputToLog = $parsed | ConvertTo-Json -Depth 50
        }
      }
    } catch {
      # if JSON parsing/formatting fails, fall back to raw output
      $outputToLog = $joined
    }
    # If output is extremely long, save to a separate file and log a pointer
    # Use the original (unsanitized/pretty) content for saving; but sanitize what we actually log
    $sanitizedForLog = Sanitize-LogOutput $joinedOriginal
    if ($outputToLog.Length -gt 8000) {
      try {
        $time = Get-Date -Format 'yyyyMMddHHmmss'
        $shortName = ([System.Guid]::NewGuid()).ToString().Substring(0,8)
        if ($PSVersionTable.PSVersion.Major -ge 3 -and $PSScriptRoot) {
          $outFile = Join-Path $PSScriptRoot "deploy-output-$time-$shortName.txt"
        } else {
          $outFile = Join-Path (Get-Location) "deploy-output-$time-$shortName.txt"
        }
        Set-Content -Path $outFile -Value $joinedOriginal -Encoding UTF8
        $outputToLog = "<output truncated; full content saved to $outFile (length=$($joinedOriginal.Length))>"
      }
      catch {
        # on any failure just keep the original
        $outputToLog = $joined
      }
    }
    # Write sanitized output to the log to avoid embedding script source
    if ([string]::IsNullOrWhiteSpace($outputToLog)) { $toWrite = $sanitizedForLog } else { $toWrite = $outputToLog }
    # If the output we plan to write still looks like source, fall back to the sanitized version
    if ($toWrite -match '^(\s*\$[a-zA-Z_]|\s*function\s+|\s*param\s*\(|\s*if\s*\()') { $toWrite = $sanitizedForLog }
    Log "Exit output: $toWrite"
    return @{ Success = $true; Output = $joined }
  }
  catch {
    $err = $_.Exception.Message
    Log "Process failed: $err"
    return @{ Success = $false; Output = $err }
  }
}

# ------------------------------------------------------------------------

$ResourceGroup      = "respondrlite"
$Location           = "eastus2"
$OpenAiLocation     = "eastus2"

$ContainerImage = "docker.io/randytreit/respondr:2025-08-25"

$DotEnvPath     = ".\.env"

$StorageAccountBase = "respondrlitesg"     # storage: 3-24, a-z0-9 only
$FunctionAppBase    = "respondrliteapp"    # app service: letters/numbers/hyphen
$ContainerAppBase   = "respondrlite-ca"    # container app: letters/numbers/hyphen
$OpenAiBase         = "respondrlite-openai" # AOAI: letters/numbers/hyphen
$StaticWebAppBase   = "respondrlite-spa"    # static web app: letters/numbers/hyphen

$baseSalt = "$ResourceGroup|$Location" # use this if you want names to be idempotent
$runId    = ([guid]::NewGuid()).ToString('N')  # 32 hex chars, no dashes

$StorageAccountName = New-UniqueStorageAccountName -BaseName $StorageAccountBase -Salt $runId
$FunctionAppName    = New-UniqueHyphenName        -BaseName $FunctionAppBase    -Salt $runId -MaxLength 60
$ContainerAppName   = New-UniqueHyphenName        -BaseName $ContainerAppBase   -Salt $runId -MaxLength 63
$OpenAiName         = New-UniqueHyphenName        -BaseName $OpenAiBase         -Salt $runId -MaxLength 64
$StaticWebAppName   = New-UniqueHyphenName        -BaseName $StaticWebAppBase   -Salt $runId -MaxLength 64

Assert-Name $StorageAccountName '^[a-z0-9]{3,24}$' 24
Assert-Name $FunctionAppName    '^[a-z0-9-]{2,60}$' 60
Assert-Name $ContainerAppName   '^[a-z0-9-]{2,63}$' 63
Assert-Name $OpenAiName         '^[a-z0-9-]{2,64}$' 64
Assert-Name $StaticWebAppName   '^[a-z0-9-]{2,64}$' 64

$names = [ordered]@{
  resourceGroup = $ResourceGroup
  storage       = $StorageAccountName
  functionApp   = $FunctionAppName
  containerApp  = $ContainerAppName
  staticWebApp  = $StaticWebAppName
  openAi        = $OpenAiName
  location      = $Location
}
$names.GetEnumerator() | ForEach-Object { Write-Host ("{0}: {1}" -f $_.Key, $_.Value) }
$names | ConvertTo-Json | Set-Content (Join-Path $PSScriptRoot 'deploy-names.json') -Encoding UTF8


# initialize/rotate log: set log path and overwrite previous log so old noisy content is not shown
if (-not $global:LogFile) {
  if ($PSVersionTable.PSVersion.Major -ge 3 -and $PSScriptRoot) {
    $global:LogFile = Join-Path $PSScriptRoot 'deploy-from-scratch.log'
  }
  else {
    $global:LogFile = Join-Path (Get-Location) 'deploy-from-scratch.log'
  }
}
# overwrite existing log with a header for this run
try {
  $header = "[" + (Get-Date -Format o) + "] Starting deploy-from-scratch.ps1 (new run)"
  Set-Content -Path $global:LogFile -Value $header -Encoding UTF8
}
catch {
  Write-Host "Warning: failed to initialize log file: $_" -ForegroundColor Yellow
}
Log "Starting deploy-from-scratch.ps1"
Log "Using storage account name: $StorageAccountName"


# from repo root (where infra\deploy.ps1 and infra\main.bicep live)
..\infra\deploy.ps1 `
  -ResourceGroup $ResourceGroup `
  -StorageAccountName $StorageAccountName `
  -FunctionAppName $FunctionAppName `
  -Location $Location `
  -OpenAiName $OpenAiName `
  -OpenAiLocation $OpenAiLocation `
  -ContainerAppName $ContainerAppName `
  -ContainerImage $ContainerImage `
  -StaticWebAppName $StaticWebAppName `
  -DotEnvPath $DotEnvPath
Log "Using direct invocation of ..\infra\deploy.ps1 (the earlier backtick call handles parameters)"

Log "Deployment script complete. Check $global:LogFile for full logs."
