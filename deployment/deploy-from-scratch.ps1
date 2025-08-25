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

$openAiName = "respondrlite-openai"
$openAiLocation = "eastus2"
$rgName = "respondrlite"
$location = "eastus2"
$storageAccountName = "respondrlitesg"
$functionAppName = "respondrliteapp"

if (-not (az group exists --name $rgName)) {
    az group create --name $rgName --location $location
}
# from repo root (where infra\deploy.ps1 and infra\main.bicep live)
..\infra\deploy.ps1 `
  -ResourceGroup respondrlite `
  -StorageAccountName respondrlitesg `
  -FunctionAppName respondrliteapp `
  -Location eastus2 `
  -OpenAiName respondrlite-openai `
  -OpenAiLocation eastus2 `
  -ContainerAppName respondrlite-ca `
  -ContainerImage "docker.io/rtreit/respondr:2025-08-25" `
  -DotEnvPath ".\.env"
