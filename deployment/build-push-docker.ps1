param(
  [string]$Repo = "randytreit/respondr",
  [string]$Dockerfile = ".\Dockerfile",
  [switch]$Deploy,
  [string]$ResourceGroup = "respondrlite"
)

Push-Location ..

$ErrorActionPreference = "Stop"
# Trim user inputs to avoid stray whitespace/CRLF causing invalid image names
$Repo = $Repo.Trim()
$Dockerfile = $Dockerfile.Trim()

if (-not $Repo -or $Repo -notmatch '^[a-z0-9]+([._-][a-z0-9]+)*/[a-z0-9]+([._-][a-z0-9]+)*$') {
  throw "Repo must look like 'namespace/name' (e.g., randytreit/respondr). Got: '$Repo'"
}

$today = Get-Date -Format "yyyy-MM-dd"
$tagPattern = '^(?<date>\d{4}-\d{2}-\d{2})\.(?<n>\d+)$'

function Get-RemoteLatestTag($repo) {
  $uri = "https://hub.docker.com/v2/repositories/$repo/tags?page_size=100&ordering=last_updated"
  try {
    $all = @()
    while ($uri) {
      $resp = Invoke-RestMethod -Uri $uri -Method GET -ErrorAction Stop
      $all += $resp.results
      $uri = $resp.next
    }
    $names = $all | ForEach-Object { $_.name } | Where-Object { [regex]::IsMatch($_, $tagPattern) }
    if (-not $names) { return $null }
    $parsed = $names | ForEach-Object {
      $m = [regex]::Match($_, $tagPattern)
      if ($m.Success) {
        [pscustomobject]@{
          Raw  = $_
          Date = [datetime]::ParseExact($m.Groups['date'].Value, "yyyy-MM-dd", $null)
          N    = [int]$m.Groups['n'].Value
        }
      }
    }
    $latest = $parsed | Sort-Object Date, N | Select-Object -Last 1
    return $latest.Raw
  } catch {
    return $null
  }
}

function Get-LocalLatestTag($repo) {
  try {
    $tags = docker image ls $repo --format "{{.Tag}}" 2>$null |
      Where-Object { [regex]::IsMatch($_, $tagPattern) }
    if (-not $tags) { return $null }
    $parsed = $tags | ForEach-Object {
      $m = [regex]::Match($_, $tagPattern)
      if ($m.Success) {
        [pscustomobject]@{
          Raw  = $_
          Date = [datetime]::ParseExact($m.Groups['date'].Value, "yyyy-MM-dd", $null)
          N    = [int]$m.Groups['n'].Value
        }
      }
    }
    $latest = $parsed | Sort-Object Date, N | Select-Object -Last 1
    return $latest.Raw
  } catch {
    return $null
  }
}

function Get-NextTag($latestTag) {
  if ($latestTag) {
    $m = [regex]::Match($latestTag, $tagPattern)
    if ($m.Success) {
      $ldate = $m.Groups['date'].Value
      $ln    = [int]$m.Groups['n'].Value
      if ($ldate -eq $today) {
        return "$ldate." + ($ln + 1)
      } else {
        return "$today.1"
      }
    }
  }
  return "$today.1"
}

 $latest = Get-RemoteLatestTag $Repo
if (-not $latest) {
  $latest = Get-LocalLatestTag $Repo
}
$nextTag = Get-NextTag $latest

Write-Host "Latest tag seen: $($latest ?? '<none>')"
Write-Host "Next tag: $nextTag"

$IMAGE = "${Repo}:${nextTag}"

# Build the image from the specified Dockerfile and tag it with the new tag
Write-Host "Building image: $IMAGE (Dockerfile: $Dockerfile)"
& docker build -t "$IMAGE" -f "$Dockerfile" .

# Verify image exists locally before tagging/pushing
try {
  & docker image inspect "$IMAGE" > $null 2>&1
} catch {
  throw "Build completed but image '$IMAGE' not found locally. Aborting push."
}

# Also tag the built image as "latest"
& docker tag "$IMAGE" "${Repo}:latest"

# Push both the new tag and the latest tag
Write-Host "Pushing: $IMAGE"
& docker push "$IMAGE"
Write-Host "Pushing: ${Repo}:latest"
& docker push "${Repo}:latest"

# Optional deployment step
if ($Deploy) {
  Write-Host ""
  Write-Host "Deploying to Azure Container App..."
  
  # Discover Container Apps in the resource group
  Write-Host "Discovering Container Apps in resource group: $ResourceGroup"
  $containerAppsJson = az containerapp list -g $ResourceGroup --query "[].{name:name, fqdn:configuration.ingress.fqdn}" -o json 2>$null
  
  if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to list Container Apps. Make sure you're logged into Azure CLI and the resource group exists." -ForegroundColor Red
    exit 1
  }
  
  $containerApps = $containerAppsJson | ConvertFrom-Json
  
  if (-not $containerApps -or $containerApps.Count -eq 0) {
    Write-Host "No Container Apps found in resource group: $ResourceGroup" -ForegroundColor Red
    exit 1
  }
  
  # Select the Container App
  if ($containerApps.Count -eq 1) {
    $AppName = $containerApps[0].name
    Write-Host "Found Container App: $AppName" -ForegroundColor Green
  } else {
    Write-Host "Multiple Container Apps found:" -ForegroundColor Yellow
    for ($i = 0; $i -lt $containerApps.Count; $i++) {
      Write-Host "  [$i] $($containerApps[$i].name) - $($containerApps[$i].fqdn)" -ForegroundColor Yellow
    }
    
    do {
      $choice = Read-Host "Select Container App by number (0-$($containerApps.Count-1))"
    } while (-not ($choice -match '^\d+$') -or [int]$choice -lt 0 -or [int]$choice -ge $containerApps.Count)
    
    $AppName = $containerApps[[int]$choice].name
    Write-Host "Selected Container App: $AppName" -ForegroundColor Green
  }
  
  $fullImageName = "docker.io/$IMAGE"
  $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
  
  Write-Host ""
  Write-Host "Deployment Details:" -ForegroundColor Cyan
  Write-Host "  Resource Group: $ResourceGroup" -ForegroundColor White
  Write-Host "  Container App: $AppName" -ForegroundColor White
  Write-Host "  Image: $fullImageName" -ForegroundColor White
  Write-Host "  Revision Suffix: rd-$stamp" -ForegroundColor White
  Write-Host ""
  
  Write-Host "Updating Container App..." -ForegroundColor Yellow
  az containerapp update -g $ResourceGroup -n $AppName `
    --image $fullImageName `
    --revision-suffix "rd-$stamp" `
    --set-env-vars REDEPLOY_AT=$stamp | Out-Null
  
  if ($LASTEXITCODE -eq 0) {
    Write-Host "Deployment successful!" -ForegroundColor Green
    
    # Get the app URL
    $fqdn = az containerapp show -g $ResourceGroup -n $AppName --query "properties.configuration.ingress.fqdn" -o tsv 2>$null
    if ($fqdn) {
      Write-Host "App URL: https://$fqdn" -ForegroundColor Cyan
    }
  } else {
    Write-Host "Deployment failed!" -ForegroundColor Red
    exit $LASTEXITCODE
  }
}
Pop-Location