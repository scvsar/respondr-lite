param(
  [Parameter(Mandatory)] [string]$ResourceGroup,
  [Parameter(Mandatory)] [string]$Environment,
  [Parameter(Mandatory)] [string]$App,
  [Parameter(Mandatory)] [string]$Domain,
  [ValidateSet('Managed','BYO')] [string]$Prefer = 'Managed',
  [string]$ByoCertName,                       # required if -Prefer BYO
  [ValidateSet('CNAME','HTTP')] [string]$ValidationMethod = 'CNAME',
  [switch]$VerboseOutput
)

# ---- safety rails -----------------------------------------------------------
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
function Out-Info([string]$msg) { if ($VerboseOutput) { Write-Host $msg -ForegroundColor Cyan } }
Write-Host "RG=$ResourceGroup ENV=$Environment APP=$App DOMAIN=$Domain Prefer=$Prefer" -ForegroundColor DarkGray

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
  throw "Azure CLI ('az') not found on PATH."
}
foreach ($p in 'ResourceGroup','Environment','App','Domain') {
  if (-not (Get-Variable -Name $p -Scope Local -ErrorAction SilentlyContinue).Value) {
    throw "Required parameter -$p was empty."
  }
}

# Helper: run AZ and return stdout; capture stderr to temp and throw on nonzero exit
function Invoke-AzJson {
  param([Parameter(Mandatory)][string]$CommandLine)
  $err = [System.IO.Path]::GetTempFileName()
  try {
    # Remove 'az' from start if present and parse command line properly
    $cleanCmd = $CommandLine -replace '^az\s+', ''
    $cmdParts = $cleanCmd -split '\s+(?=(?:[^"]|"[^"]*")*$)'
    $cleanParts = @()
    foreach ($part in $cmdParts) {
      if ($part.Trim()) {
        $cleanParts += $part.Trim('"')
      }
    }
    
    # Add output format
    $cleanParts += @('-o', 'json')
    
    Out-Info "Running: az $($cleanParts -join ' ')"
    $out = & az @cleanParts 2>$err
    
    if ($LASTEXITCODE -ne 0) {
      $msg = (Get-Content $err -Raw -EA SilentlyContinue)
      if (-not $msg) { $msg = "(no stderr captured)" }
      throw $msg
    }
    return $out
  } finally {
    Remove-Item $err -EA SilentlyContinue
  }
}

# ---- fetch cert inventory ---------------------------------------------------
Out-Info "Listing certificates in environment '$Environment'..."
$certsJson = Invoke-AzJson "az containerapp env certificate list -g `"$ResourceGroup`" -n `"$Environment`""
$certs = $certsJson | ConvertFrom-Json

# Choose the certificate
$managed = $certs | Where-Object {
  $_.type -like "*managedEnvironments/managedCertificates" `
  -and $_.properties.subjectName -eq $Domain `
  -and $_.properties.provisioningState -eq "Succeeded"
}
$byo = $null
if ($Prefer -eq 'BYO') {
  if (-not $ByoCertName) { throw "Specify -ByoCertName when -Prefer BYO." }
  $byo = $certs | Where-Object {
    $_.type -like "*managedEnvironments/certificates" `
    -and $_.name -eq $ByoCertName
  }
  if (-not $byo) { throw "BYO cert '$ByoCertName' not found in environment '$Environment'." }
}

$chosen = if ($Prefer -eq 'Managed') { $managed } else { $byo }
if ($chosen) {
  Out-Info "Selected cert: $($chosen.name)  [$($chosen.type)]"
} elseif ($Prefer -eq 'Managed') {
  Out-Info "No managed cert found for $Domain; will let ACA create one during bind (validation: $ValidationMethod)."
} else {
  throw "No certificate selected."
}

# ---- ensure hostname exists on the app -------------------------------------
Out-Info "Checking existing hostnames on app '$App'..."
$hostListJson = Invoke-AzJson "az containerapp hostname list -g `"$ResourceGroup`" -n `"$App`""
$existingHostnames = $hostListJson | ConvertFrom-Json
$exists = @($existingHostnames | Where-Object { $_.name -eq $Domain }).Count -gt 0

if (-not $exists) {
  Out-Info "Hostname not present; adding $Domain"
  $null = Invoke-AzJson "az containerapp hostname add -g `"$ResourceGroup`" -n `"$App`" --hostname `"$Domain`""
  Out-Info "Hostname added: $Domain"
} else {
  Out-Info "Hostname already present: $Domain"
}

# ---- bind certificate -------------------------------------------------------
Out-Info "Binding certificate to hostname..."
if ($chosen) {
  $cmdLine = "az containerapp hostname bind -g `"$ResourceGroup`" -n `"$App`" --hostname `"$Domain`" --environment `"$Environment`" --certificate `"$($chosen.id)`""
  $bindJson = Invoke-AzJson $cmdLine
} else {
  # Let ACA create/attach a managed cert during bind
  $cmdLine = "az containerapp hostname bind -g `"$ResourceGroup`" -n `"$App`" --hostname `"$Domain`" --environment `"$Environment`" --validation-method $ValidationMethod"
  $bindJson = Invoke-AzJson $cmdLine
}
$bind = $bindJson | ConvertFrom-Json

# ---- summaries --------------------------------------------------------------
Write-Host ""
Write-Host "=== Binding Result ===" -ForegroundColor Green
$bind | ForEach-Object {
  [pscustomobject]@{
    Hostname      = $_.name
    BindingType   = $_.bindingType
    CertificateId = $_.certificateId
  }
} | Format-Table -AutoSize

Write-Host ""
Write-Host "=== App Hostnames ===" -ForegroundColor Green
az containerapp hostname list -g $ResourceGroup -n $App -o table

Write-Host ""
Write-Host "=== Environment Certificates ===" -ForegroundColor Green
az containerapp env certificate list -g $ResourceGroup -n $Environment -o table
