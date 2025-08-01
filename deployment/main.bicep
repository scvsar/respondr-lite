@description('The location of the resources.')
param location string = resourceGroup().location

@description('A prefix for resource names to ensure uniqueness')
param resourcePrefix string = 'response'

@description('The name of the AKS cluster.')
param aksClusterName string = '${resourcePrefix}-aks-cluster'

@description('The name of the Azure OpenAI account.')
param openAiAccountName string = '${resourcePrefix}-openai-account'

@description('The SKU for the Azure OpenAI account.')
param openAiSku string = 'S0'

@description('The name of the Azure Container Registry.')
param acrName string = '${resourcePrefix}${uniqueString(resourceGroup().id)}acr'

@description('The name of the Azure Storage Account.')
param storageAccountName string = 'resp${uniqueString(resourceGroup().id)}store'

@description('The SKU for the Azure Storage Account.')
param storageAccountSku string = 'Standard_LRS'

resource aksCluster 'Microsoft.ContainerService/managedClusters@2023-08-01' = {
  name: aksClusterName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    dnsPrefix: '${aksClusterName}-dns'
    agentPoolProfiles: [
      {
        name: 'agentpool'
        count: 1
        vmSize: 'Standard_DS2_v2'
        osType: 'Linux'
        mode: 'System'
      }
    ]
  }
}

resource openAiAccount 'Microsoft.CognitiveServices/accounts@2023-05-01' = {
  name: openAiAccountName
  location: location
  sku: {
    name: openAiSku
  }
  kind: 'OpenAI'
  properties: {
    publicNetworkAccess: 'Enabled'
  }
}

resource acr 'Microsoft.ContainerRegistry/registries@2021-06-01-preview' = {
  name: acrName
  location: location
  sku: {
    name: 'Standard'
  }
  properties: {
    adminUserEnabled: true
  }
}

// Create role assignment to allow AKS to pull from ACR
resource acrPullRole 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = {
  name: guid(resourceGroup().id, aksCluster.id, 'acrpull')
  scope: acr
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d') // AcrPull role
    principalId: aksCluster.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// Create Azure Storage Account
resource storageAccount 'Microsoft.Storage/storageAccounts@2022-09-01' = {
  name: storageAccountName
  location: location
  sku: {
    name: storageAccountSku
  }
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
    supportsHttpsTrafficOnly: true
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Allow'
    }
  }
}

// Create a blob service for the storage account
resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2022-09-01' = {
  parent: storageAccount
  name: 'default'
  properties: {
    cors: {
      corsRules: []
    }
    deleteRetentionPolicy: {
      enabled: false
    }
  }
}

// Create a container in the blob service
resource container 'Microsoft.Storage/storageAccounts/blobServices/containers@2022-09-01' = {
  parent: blobService
  name: 'responses'
  properties: {
    publicAccess: 'None'
  }
}

// Outputs for resource names and endpoints
output aksClusterName string = aksCluster.name
output acrName string = acr.name
output openAiAccountName string = openAiAccount.name
output storageAccountName string = storageAccount.name
output storageAccountBlobEndpoint string = storageAccount.properties.primaryEndpoints.blob
