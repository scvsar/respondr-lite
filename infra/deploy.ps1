# deploy.ps1
#!/usr/bin/env pwsh
param(
  [Parameter(Mandatory = $true)] [string]$ResourceGroup,
  [Parameter(Mandatory = $true)] [string]$StorageAccountName,
  [Parameter(Mandatory = $true)] [string]$FunctionAppName,
  [Parameter(Mandatory = $true)] [string]$Location,
  [Parameter(Mandatory = $true)] [string]$OpenAiName,
  [Parameter(Mandatory = $true)] [string]$OpenAiLocation,

  # NEW: Container App params
  [Parameter(Mandatory = $true)] [string]$ContainerAppName,
  [Parameter(Mandatory = $true)] [string]$ContainerImage,
  [int]$ContainerPort = 8000,
  [int]$HttpConcurrent = 50,
  [int]$CooldownSeconds = 7200,
  [int]$PollingSeconds = 30,
  [int]$MaxReplicas = 5,
  [int]$MinReplicas = 0,
  [string]$DotEnvPath = ".env"
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# run the main deploy operations inside a try/catch to avoid PowerShell printing script source
try {
  Write-Host "Registering providers if needed..."
  az provider register --namespace Microsoft.CognitiveServices | Out-Null
  az provider register --namespace Microsoft.App | Out-Null
  az provider register --namespace Microsoft.OperationalInsights | Out-Null

  Write-Host "Ensuring resource group '$ResourceGroup' exists..."
  az group create -n $ResourceGroup -l $Location | Out-Null

# --- Parse .env into plain env + secrets ---
function Parse-DotEnv([string]$path) {
  $plain = @()
  $secretMap = @{}

  if (-not (Test-Path $path)) {
    return @{ Plain = $plain; SecretMap = $secretMap }
  }

  # Treat typical secret-looking keys as secrets
  $secretKeyPattern = '(?i)(^|_)(SECRET|TOKEN|PASSWORD|APIKEY|API_KEY|CONNSTR|CONNECTION|SAS|PRIVATE(KEY)?|CERT|PWD|KEY)$'

  Get-Content $path | ForEach-Object {
    $line = $_.Trim()
    if ([string]::IsNullOrWhiteSpace($line) -or $line.StartsWith('#')) { return }
    $kv = $line -split '=', 2
    if ($kv.Count -lt 2) { return }
    $k = $kv[0].Trim()
    $v = $kv[1].Trim().Trim('"').Trim("'")
    if ($k -match $secretKeyPattern) {
      $secretMap[$k] = $v
    } else {
      $plain += @{ name = $k; value = $v }
    }
  }

  return @{ Plain = $plain; SecretMap = $secretMap }
}

$envParsed = Parse-DotEnv -path $DotEnvPath
$plainEnv = $envParsed.Plain
$secretMap = $envParsed.SecretMap

# Build a temp parameters file so we can pass complex arrays/objects cleanly
$tempParams = Join-Path $env:TEMP "aca-params-$($ContainerAppName)-$(Get-Date -Format 'yyyyMMddHHmmss').json"

@{
  saName            = @{ value = $StorageAccountName }
  functionAppName   = @{ value = $FunctionAppName }
  location          = @{ value = $Location }
  openAiName        = @{ value = $OpenAiName }
  openAiLocation    = @{ value = $OpenAiLocation }

  # Container App
  containerAppName         = @{ value = $ContainerAppName }
  containerImage           = @{ value = $ContainerImage }
  containerPort            = @{ value = $ContainerPort }
  httpConcurrentRequests   = @{ value = $HttpConcurrent }
  cooldownSeconds          = @{ value = $CooldownSeconds }
  pollingIntervalSeconds   = @{ value = $PollingSeconds }
  containerMaxReplicas     = @{ value = $MaxReplicas }
  containerMinReplicas     = @{ value = $MinReplicas }
  containerEnvPlain        = @{ value = $plainEnv }
  containerSecretMap       = @{ value = $secretMap }
} | ConvertTo-Json -Depth 50 | Set-Content -Encoding UTF8 $tempParams


  Write-Host "Starting deployment..."
  az deployment group create `
    --resource-group $ResourceGroup `
    --template-file "$scriptDir/main.bicep" `
    --parameters `@"$tempParams"

  Remove-Item $tempParams -Force
  Write-Host "Deployment complete."

} catch {
  # Save full exception details to a file and emit a concise message only
  $ex = $_.Exception
  $time = Get-Date -Format 'yyyyMMddHHmmss'
  try {
    $errFile = Join-Path $scriptDir "deploy-error-$time.txt"
    $ex.ToString() | Out-File -FilePath $errFile -Encoding UTF8
    Write-Host "ERROR: Deployment failed. Full details saved to $errFile"
  }
  catch {
    Write-Host "ERROR: Deployment failed. (Failed to write error file)"
  }
  # exit with non-zero code so callers know it failed
  exit 1
}
