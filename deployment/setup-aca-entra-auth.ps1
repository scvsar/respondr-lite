[CmdletBinding()]
param(
  [Parameter(Mandatory)] [string]$ResourceGroup,
  [string]$ContainerAppName,                 # optional; auto-discovers first CA in RG
  [string]$AppDisplayName = "respondrlite-containerapp-auth",
  [switch]$IncludeMSA,                       # if set -> AzureADandPersonalMicrosoftAccount (uses 'common')
  [string]$ClientSecretName = "aad-client-secret",
  [int]$RenewIfExpiresInDays = 30,           # rotate secret if none valid beyond N days
  [string[]]$ExtraRedirectUris = @()         # add custom domains etc. if you have them
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Log([string]$m) { Write-Host ("[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $m) }
function Warn([string]$m) { Write-Warning $m }

# --- 1) Discover Container App + FQDN -------------------------------------------------
if (-not $ContainerAppName) {
  Log "Discovering Container App in RG '$ResourceGroup'..."
  $ContainerAppName = az containerapp list -g $ResourceGroup --query "[0].name" -o tsv
  if ([string]::IsNullOrWhiteSpace($ContainerAppName)) {
    throw "No Container Apps found in resource group '$ResourceGroup'."
  }
  Log "Using Container App: $ContainerAppName"
}

$ca = az containerapp show -g $ResourceGroup -n $ContainerAppName --only-show-errors | ConvertFrom-Json
# FQDN lives here for CLI output:
$fqdn = $ca.properties.configuration.ingress.fqdn
if ([string]::IsNullOrWhiteSpace($fqdn)) {
  throw "Ingress/FQDN not found. Ensure ingress is enabled for Container App '$ContainerAppName'."
}
$redirect = "https://$fqdn/.auth/login/aad/callback"
Log "Computed redirect URI: $redirect"

# --- 2) Find or create the App Registration ------------------------------------------
# Exact-match by displayName; avoid the CLI --display-name wildcard behavior.
$filter = "displayName eq '$AppDisplayName'"
$appListJson = az ad app list --filter "$filter" --only-show-errors
$appList = @()
if (-not [string]::IsNullOrWhiteSpace($appListJson)) { 
  # Force the result into an array to handle single object case
  $appList = @($appListJson | ConvertFrom-Json)
}
if ($appList.Count -gt 1) { Warn "Multiple app registrations named '$AppDisplayName'; using the first." }

$app = $null
if ($appList.Count -ge 1) {
  $app = $appList[0]
  Log "Found existing app registration: $($app.appId)"
} else {
  $aud = $(if ($IncludeMSA) { "AzureADandPersonalMicrosoftAccount" } else { "AzureADMultipleOrgs" })
  Log "Creating new app registration '$AppDisplayName' (audience=$aud)..."
  $app = az ad app create `
          --display-name "$AppDisplayName" `
          --sign-in-audience $aud `
          --web-redirect-uris $redirect `
          --only-show-errors | ConvertFrom-Json
  Log "Created appId: $($app.appId)"
}

$appId = $app.appId
if ([string]::IsNullOrWhiteSpace($appId)) { throw "appId not resolved." }

# --- 3) Ensure sign-in audience & redirect URIs ---------------------------------------
$desiredAudience = $(if ($IncludeMSA) { "AzureADandPersonalMicrosoftAccount" } else { "AzureADMultipleOrgs" })
if ($app.signInAudience -ne $desiredAudience) {
  Log "Updating sign-in audience to $desiredAudience"
  az ad app update --id $appId --sign-in-audience $desiredAudience --only-show-errors | Out-Null
}

# Merge existing web.redirectUris with the Container App's redirect + any extras
$currentUris = @()
try {
  $currentUris = @(az ad app show --id $appId --query "web.redirectUris" -o json --only-show-errors | ConvertFrom-Json)
  # Handle case where the result is null
  if ($null -eq $currentUris) { $currentUris = @() }
} catch { $currentUris = @() }

$needUris = @($redirect) + $ExtraRedirectUris | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique
$merged = @(($currentUris + $needUris) | Select-Object -Unique)

# Only update if something new is added
$mergedArray = @($merged)
$currentUrisArray = @($currentUris)
$newUris = @($merged | Where-Object { $_ -notin $currentUrisArray })
if ($mergedArray.Count -ne $currentUrisArray.Count -or $newUris.Count -gt 0) {
  Log "Updating redirect URIs (additive merge)"
  # Pass as space-separated list
  $urisArg = ($merged -join " ")
  az ad app update --id $appId --web-redirect-uris $urisArg --only-show-errors | Out-Null
}

# --- 4) Ensure a usable client secret -------------------------------------------------
function Get-ValidSecret([string]$appId, [int]$minDays) {
  $credsJson = az ad app credential list --id $appId --only-show-errors
  if ([string]::IsNullOrWhiteSpace($credsJson)) { return $null }
  
  $creds = $credsJson | ConvertFrom-Json
  if (-not $creds) { return $null }
  
  # Ensure $creds is treated as an array
  $creds = @($creds)
  $deadline = (Get-Date).AddDays($minDays)
  
  foreach ($c in $creds) {
    if ($c -and $c.endDateTime) {
      # endDateTime is ISO 8601
      try {
        $end = Get-Date $c.endDateTime
        if ($end -gt $deadline) { return $c }
      } catch {
        # Skip invalid date entries
        continue
      }
    }
  }
  return $null
}

$valid = Get-ValidSecret $appId $RenewIfExpiresInDays
$clientSecret = $null
if (-not $valid) {
  Log "No valid long-lived secret found; creating a new client secret (2 years)..."
  # NOTE: Command returns the *password* (client secret) in plain text; keep it in memory only.
  $clientSecret = az ad app credential reset --id $appId `
                   --years 2 `
                   --query password -o tsv --only-show-errors
  if ([string]::IsNullOrWhiteSpace($clientSecret)) { throw "Failed to create client secret." }
  Log "Client secret created."
} else {
  Log "Reusing existing client secret (expires $($valid.endDateTime))."
}

# --- 5) Put/refresh the secret in the Container App & wire the provider ---------------
if ($clientSecret) {
  Log "Storing secret in Container App secrets as '$ClientSecretName' (value not logged)..."
  az containerapp secret set -g $ResourceGroup -n $ContainerAppName `
     --secrets "$ClientSecretName=$clientSecret" --only-show-errors | Out-Null
} else {
  # Even when reusing existing secret, we need to ensure it exists in Container App
  # Check if secret exists in Container App
  $existingSecrets = az containerapp secret list -g $ResourceGroup -n $ContainerAppName --query "[].name" -o tsv --only-show-errors
  if ($existingSecrets -notcontains $ClientSecretName) {
    Log "Secret '$ClientSecretName' not found in Container App. Need to regenerate client secret..."
    # Force regeneration of client secret
    $clientSecret = az ad app credential reset --id $appId `
                     --years 2 `
                     --query password -o tsv --only-show-errors
    if ([string]::IsNullOrWhiteSpace($clientSecret)) { throw "Failed to create client secret." }
    Log "Client secret created."
    
    Log "Storing secret in Container App secrets as '$ClientSecretName' (value not logged)..."
    az containerapp secret set -g $ResourceGroup -n $ContainerAppName `
       --secrets "$ClientSecretName=$clientSecret" --only-show-errors | Out-Null
  } else {
    Log "Secret '$ClientSecretName' already exists in Container App."
  }
}

# Issuer for multi-tenant: organizations (AAD accounts only). If including MSA, use common.
$issuer = $(if ($IncludeMSA) { "https://login.microsoftonline.com/common/v2.0" } else { "https://login.microsoftonline.com/organizations/v2.0" })

Log "Configuring Microsoft provider (clientId=$appId, issuer=$issuer)..."
az containerapp auth microsoft update -g $ResourceGroup -n $ContainerAppName `
   --client-id $appId `
   --client-secret-name $ClientSecretName `
   --issuer $issuer `
   --only-show-errors | Out-Null

# --- 6) Enable Easy Auth, set redirect behavior ---------------------------------------
Log "Enabling Easy Auth and setting unauthenticated action to RedirectToLoginPage..."
az containerapp auth update -g $ResourceGroup -n $ContainerAppName `
   --enabled true `
   --redirect-provider microsoft `
   --unauthenticated-client-action RedirectToLoginPage `
   --only-show-errors | Out-Null

# --- 7) Show summary ------------------------------------------------------------------
$final = az containerapp auth show -g $ResourceGroup -n $ContainerAppName --only-show-errors | ConvertFrom-Json
Log ""
Log "=== DONE =============================================================="
Log "Container App:   $ContainerAppName"
Log "App displayName: $AppDisplayName"
Log "App (client) ID: $appId"
Log "Issuer:          $issuer"
Log "Login URL:       https://$fqdn/.auth/login/aad"
Log "Callback URL:    $redirect"
Log "======================================================================="