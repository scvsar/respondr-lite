# create the resource group if it doesn't exist using az cli
$rgName = "respondrlite"
$location = "eastus2"
$storageAccountName = "respondrlitesg"
$functionAppName = "respondrliteapp"
if (-not (az group exists --name $rgName)) {
    az group create --name $rgName --location $location
}
# from repo root (where infra\deploy.ps1 and infra\main.bicep live)
..\infra\deploy.ps1 -ResourceGroup $rgName -StorageAccountName $storageAccountName -FunctionAppName $functionAppName -Location $location