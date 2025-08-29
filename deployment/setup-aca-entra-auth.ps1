[CmdletBinding()]
param(
  [Parameter(Mandatory)] [string]$ResourceGroup,
  [string]$ContainerAppName,                 # optional; auto-discovers first CA in RG
  [string]$AppDisplayName = "respondrlite-containerapp-auth",
  [switch]$IncludeMSA,                       # if set -> AzureADandPersonalMicrosoftAccount (issuer = common)
  [string]$ClientSecretName = "aad-client-secret",
  [int]$RenewIfExpiresInDays = 30,           # rotate secret if none valid beyond N days
  [string[]]$ExtraRedirectUris = @()         # add custom domains etc. if you have them
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Log([string]$m) { Write-Host ("[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $m) }
function Warn([string]$m) { Write-Warning $m }

# --- 1) Discover Container App + FQDN -----------------------------------------------
if (-not $ContainerAppName) {
  Log "Discovering Container App in RG '$ResourceGroup'..."
  $ContainerAppName = az containerapp list -g $ResourceGroup --query "[0].name" -o tsv
  if ([string]::IsNullOrWhiteSpace($ContainerAppName)) {
    throw "No Container Apps found in resource group '$ResourceGroup'."
  }
  Log "Using Container App: $ContainerAppName"
}

$ca   = az containerapp show -g $ResourceGroup -n $ContainerAppName --only-show-errors | ConvertFrom-Json
$fqdn = $ca.properties.configuration.ingress.fqdn
if ([string]::IsNullOrWhiteSpace($fqdn)) {
  throw "Ingress/FQDN not found. Ensure ingress is enabled for '$ContainerAppName'."
}
$redirect = "https://$fqdn/.auth/login/aad/callback"
Log "Computed redirect URI: $redirect"

# --- 2) Find or create the App Registration (multi-tenant by default) ----------------
$filter = "displayName eq '$AppDisplayName'"
$appRegListJson = az ad app list --filter "$filter" --only-show-errors
$appRegList = @()
if (-not [string]::IsNullOrWhiteSpace($appRegListJson)) { $appRegList = @($appRegListJson | ConvertFrom-Json) }
if ($appRegList.Count -gt 1) { Warn "Multiple app registrations named '$AppDisplayName'; using the first." }

$appReg = $null
if ($appRegList.Count -ge 1) {
  $appReg = $appRegList[0]
  Log "Found existing app registration: $($appReg.appId)"
} else {
  $aud = $(if ($IncludeMSA) { "AzureADandPersonalMicrosoftAccount" } else { "AzureADMultipleOrgs" })
  Log "Creating new app registration '$AppDisplayName' (audience=$aud)..."
  $appReg = az ad app create `
            --display-name "$AppDisplayName" `
            --sign-in-audience $aud `
            --web-redirect-uris $redirect `
            --only-show-errors | ConvertFrom-Json
  Log "Created appId: $($appReg.appId)"
}
$appId = $appReg.appId
if ([string]::IsNullOrWhiteSpace($appId)) { throw "appId not resolved." }

# Ensure v2 token acceptance and proper audience configuration
try {
  # Get current app configuration
  $currentApp = az ad app show --id $appId --query "{accessTokenAcceptedVersion: accessTokenAcceptedVersion, signInAudience: signInAudience}" --only-show-errors | ConvertFrom-Json
  
  # Update access token version if needed
  if ($currentApp.accessTokenAcceptedVersion -ne 2) {
    Log "Updating access token version to v2"
    az ad app update --id $appId --set accessTokenAcceptedVersion=2 --only-show-errors | Out-Null
  }
  
  # Update audience if needed
  $desiredAudience = $(if ($IncludeMSA) { "AzureADandPersonalMicrosoftAccount" } else { "AzureADMultipleOrgs" })
  if ($currentApp.signInAudience -ne $desiredAudience) {
    Log "Updating sign-in audience to $desiredAudience"
    az ad app update --id $appId --sign-in-audience $desiredAudience --only-show-errors | Out-Null
  }
} catch {
  Log "Warning: Could not update app registration properties. This may not affect functionality."
}

# --- 3) Ensure redirect URIs and token issuance --------------------------------------
$currentUris = @()
try {
  $currentUris = @(az ad app show --id $appId --query "web.redirectUris" -o json --only-show-errors | ConvertFrom-Json)
  if ($null -eq $currentUris) { $currentUris = @() }
} catch { $currentUris = @() }

$needUris = @($redirect) + $ExtraRedirectUris | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique
$merged   = @(($currentUris + $needUris) | Select-Object -Unique)
if ($merged.Count -ne $currentUris.Count -or (@($merged | Where-Object { $_ -notin $currentUris })).Count -gt 0) {
  Log "Updating redirect URIs (additive merge)"
  az ad app update --id $appId --web-redirect-uris ($merged -join ' ') --only-show-errors | Out-Null
}

# Make sure the app issues ID + access tokens (some tenants have these off by default)
az ad app update --id $appId --enable-id-token-issuance true --enable-access-token-issuance true --only-show-errors | Out-Null

# --- 4) Ensure a usable client secret (reuse if far from expiry) ---------------------
function Get-ValidSecret([string]$id, [int]$minDays) {
  $j = az ad app credential list --id $id --only-show-errors
  if ([string]::IsNullOrWhiteSpace($j)) { return $null }
  $creds = @($j | ConvertFrom-Json)
  $deadline = (Get-Date).AddDays($minDays)
  foreach ($c in $creds) {
    if ($c -and $c.endDateTime) {
      try {
        $end = Get-Date $c.endDateTime
        if ($end -gt $deadline) { return $c }
      } catch { }
    }
  }
  return $null
}

$valid        = Get-ValidSecret $appId $RenewIfExpiresInDays
$clientSecret = $null
if (-not $valid) {
  Log "No valid long-lived secret found; creating a new client secret (2 years)..."
  $clientSecret = az ad app credential reset --id $appId --years 2 --query password -o tsv --only-show-errors
  if ([string]::IsNullOrWhiteSpace($clientSecret)) { throw "Failed to create client secret." }
  Log "Client secret created."
} else {
  Log "Reusing existing client secret (expires $($valid.endDateTime))."
}

# Ensure secret exists in Container App secrets
if ($clientSecret) {
  Log "Storing secret in Container App secrets as '$ClientSecretName' (value not logged)..."
  az containerapp secret set -g $ResourceGroup -n $ContainerAppName --secrets "$ClientSecretName=$clientSecret" --only-show-errors | Out-Null
} else {
  $existingSecrets = az containerapp secret list -g $ResourceGroup -n $ContainerAppName --query "[].name" -o tsv --only-show-errors
  if ($existingSecrets -notcontains $ClientSecretName) {
    Log "Secret '$ClientSecretName' not found; creating a new client secret..."
    $clientSecret = az ad app credential reset --id $appId --years 2 --query password -o tsv --only-show-errors
    if ([string]::IsNullOrWhiteSpace($clientSecret)) { throw "Failed to create client secret." }
    az containerapp secret set -g $ResourceGroup -n $ContainerAppName --secrets "$ClientSecretName=$clientSecret" --only-show-errors | Out-Null
  } else {
    Log "Secret '$ClientSecretName' already exists in Container App."
  }
}

# --- 5) Configure the Microsoft provider in Container Apps ----------------------------
$issuer   = "https://login.microsoftonline.com/common/v2.0"

Log "Configuring Microsoft provider (clientId=$appId, issuer=$issuer)..."
try {
  $msArgs = @(
    "containerapp","auth","microsoft","update",
    "-g",$ResourceGroup,"-n",$ContainerAppName,
    "--client-id",$appId,
    "--issuer",$issuer
  )
  # Only supply the plaintext secret when we just created/rotated it
  if ($clientSecret) { 
    Log "Adding client secret to Microsoft provider configuration..."
    $msArgs += @("--client-secret", $clientSecret, "--yes") 
  }
  az @msArgs --only-show-errors | Out-Null
  Log "Microsoft provider configured successfully"
} catch {
  throw "Failed to configure Microsoft provider: $_"
}

# --- 6) Enable Easy Auth & default behavior ------------------------------------------
Log "Enabling Easy Auth and setting unauthenticated action to RedirectToLoginPage..."
try {
  az containerapp auth update -g $ResourceGroup -n $ContainerAppName `
    --enabled true `
    --redirect-provider microsoft `
    --unauthenticated-client-action RedirectToLoginPage `
    --only-show-errors | Out-Null
  Log "Easy Auth enabled successfully"
} catch {
  throw "Failed to enable Easy Auth: $_"
}

# --- 7) Final verification ------------------------------------------------------------
Log "Verifying configuration..."
try {
  $fqdn = az containerapp show -g $ResourceGroup -n $ContainerAppName --query "properties.configuration.ingress.fqdn" -o tsv --only-show-errors
  if ([string]::IsNullOrWhiteSpace($fqdn)) {
    throw "Could not retrieve Container App FQDN"
  }
  
  # Verify auth is enabled
  $authEnabled = az containerapp auth show -g $ResourceGroup -n $ContainerAppName --query "properties.globalValidation.requireAuthentication" -o tsv --only-show-errors 2>$null
  
  $redirect = "https://$fqdn/.auth/login/aad/callback"
  
  Log ""
  Log "=== CONFIGURATION COMPLETE ==========================================="
  Log "Container App:     $ContainerAppName"
  Log "App displayName:   $AppDisplayName"
  Log "App (client) ID:   $appId"
  Log "Issuer:            $issuer"
  Log "Authentication:    $(if ($authEnabled -eq 'true') { 'Enabled' } else { 'Enabled (verify manually)' })"
  Log "Login URL:         https://$fqdn/.auth/login/aad?post_login_redirect_uri=/"
  Log "Callback URL:      $redirect"
  Log ""
  Log "Next steps:"
  Log "1. Add the callback URL to your Entra app registration if not already present"
  Log "2. Test authentication by visiting: https://$fqdn"
  Log "3. For dual auth, deploy with ENABLE_LOCAL_AUTH=true"
  Log "======================================================================="
  
} catch {
  Log "Warning: Could not verify final configuration, but setup should be complete"
  Log "Manual verification recommended"
}
