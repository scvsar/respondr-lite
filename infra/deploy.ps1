# deploy.ps1
#!/usr/bin/env pwsh
param(
    [Parameter(Mandatory = $true)] [string]$ResourceGroup,
    [Parameter(Mandatory = $true)] [string]$StorageAccountName,
    [Parameter(Mandatory = $true)] [string]$FunctionAppName,
    [Parameter(Mandatory = $true)] [string]$Location,
    [Parameter(Mandatory = $true)] [string]$OpenAiName,
    [Parameter(Mandatory = $true)] [string]$OpenAiLocation
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

az group create -n $ResourceGroup -l $Location | Out-Null
az provider register --namespace Microsoft.CognitiveServices | Out-Null

az deployment group create `
  --resource-group $ResourceGroup `
  --template-file "$scriptDir/main.bicep" `
  --parameters `
    saName=$StorageAccountName `
    functionAppName=$FunctionAppName `
    location=$Location `
    openAiName=$OpenAiName `
    openAiLocation=$OpenAiLocation 
