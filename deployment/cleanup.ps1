<#
cleanup.ps1
Fully deletes an application RG, waits for AKS‑managfunction Purge-CognitiveAccounts {
    param([string]$Prefix)

    Write-Host "Checking for soft‑deleted Cognitive Services accounts ..."
    $deleted = az cognitiveservices account list-deleted -o json |  Write-Host "Checking for soft‑deleted Cognitive Services accounts ..."   Write-Host "Checking for soft‑deleted Cognitive Services accounts ..."ode‑RG auto‑deletion,
and purges any soft‑deleted Cognitive Services / Azure OpenAI accounts that
start with a given prefix.

Required: Azure CLI ≥ 2.60 (GA purge command).
#>

param(
    [Parameter(Mandatory)][string]$ResourceGroupName,
    [switch]$Force,
    [string]$PurgeSoftDeleted = $null,   # prefix, e.g. "respondr-"
    [int]   $TimeoutSeconds    = 0,      # 0 = wait forever
    [switch]$DeleteTempRgAfterPurge      # remove helper RG after purge
)

### ---------- helper functions ----------

function Get-RgFromId {
    param([string]$Id)
    $parts = $Id -split '/'
    $idx = [Array]::IndexOf($parts,'resourceGroups')
    if ($idx -ge 0 -and $idx + 1 -lt $parts.Length) { return $parts[$idx+1] }
    return $null
}

function Wait-ForRgDeletion {
    param([string]$Name,[int]$Timeout)
    $sw=[Diagnostics.Stopwatch]::StartNew()
    Write-Host "Waiting for resource group '$Name' to be deleted ..."
    while ((az group exists --name $Name | ConvertFrom-Json)) {
        if ($Timeout -and $sw.Elapsed.TotalSeconds -gt $Timeout) {
            throw "Timed out waiting for RG '$Name' to delete."
        }
        Start-Sleep 10
    }
    Write-Host "Resource group '$Name' is gone." -ForegroundColor Green
}

function Wait-ForAksNodeRg {
    param([string]$MainRg,[int]$Timeout)
    $sw=[Diagnostics.Stopwatch]::StartNew()
    Write-Host "Waiting for AKS‑managed node RG to disappear ..."
    while ($true) {
        $nodeRg = (az group list -o json | ConvertFrom-Json |
                   Where-Object { $_.name -like "MC_${MainRg}_*" }).name
        if (-not $nodeRg) { break }
        if ($Timeout -and $sw.Elapsed.TotalSeconds -gt $Timeout) {
            throw "Timed out waiting for node RG '$nodeRg' to delete."
        }
        Start-Sleep 15
    }
    Write-Host "AKS node RG is gone." -ForegroundColor Green
}

function Ensure-RgExists {
    param([string]$Name,[string]$Location)
    if (-not $Name) { return $false }
    if (-not (az group exists --name $Name | ConvertFrom-Json)) {
        Write-Host "Re‑creating RG '$Name' in $Location for purge ..."
        az group create --name $Name --location $Location | Out-Null
        return $true
    }
    return $false
}

function Purge-CognitiveAccounts {
    param([string]$Prefix)

    Write-Host "🔍 Checking for soft‑deleted Cognitive Services accounts ..."
    $deleted = az cognitiveservices account list-deleted -o json |
               ConvertFrom-Json |
               Where-Object { $_.name -like "${Prefix}*" }

    if (-not $deleted) { Write-Host "No soft‑deleted accounts found."; return }

    foreach ($acct in $deleted) {
        $rg  = if ($acct.resourceGroup) { $acct.resourceGroup } else { Get-RgFromId $acct.id }
        $loc = $acct.location
        $needCleanup = Ensure-RgExists -Name $rg -Location $loc
        Write-Host "Purging '$($acct.name)' (RG $rg, $loc) ..."
        az cognitiveservices account purge --name $acct.name --resource-group $rg --location $loc 
        if ($needCleanup -and $DeleteTempRgAfterPurge) {
            az group delete --name $rg --yes --no-wait
        }
    }
    Write-Host "Purge completed." -ForegroundColor Green
}

### ---------- main flow ----------

if (-not $Force) {
    Write-Host "This will DELETE '$ResourceGroupName' and wait for AKS cleanup." -ForegroundColor Yellow
    if ($PurgeSoftDeleted) { Write-Host "    It will PURGE soft‑deleted accounts starting '$PurgeSoftDeleted'." }
    if ((Read-Host "Proceed? (y/n)") -ne 'y') { return }
}

Write-Host "`nDeleting resource group '$ResourceGroupName' ..."
az group delete --name $ResourceGroupName --yes
Wait-ForRgDeletion -Name $ResourceGroupName -Timeout $TimeoutSeconds
Wait-ForAksNodeRg  -MainRg $ResourceGroupName -Timeout $TimeoutSeconds
if ($PurgeSoftDeleted) { Purge-CognitiveAccounts -Prefix $PurgeSoftDeleted }

Write-Host "`nCleanup complete – environment is ready for redeployment." -ForegroundColor Green
