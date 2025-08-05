@description('The location of the resources.')
param location string = resourceGroup().location

@description('A prefix for resource names to ensure uniqueness')
param resourcePrefix string = 'respondr'

@description('The name of the AKS cluster.')
param aksClusterName string = '${resourcePrefix}-aks-cluster-v2'

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

@description('Name of the user-assigned managed identity used by pods via workload identity')
param podIdentityName string = '${resourcePrefix}-pod-identity'

@description('The address space for the virtual network')
param vnetAddressPrefix string = '10.0.0.0/16'

@description('The subnet address space for AKS nodes')
param aksSubnetAddressPrefix string = '10.0.1.0/24'

@description('The subnet address space for Application Gateway')
param appGwSubnetAddressPrefix string = '10.0.2.0/24'

// Create Virtual Network for AKS and Application Gateway
resource vnet 'Microsoft.Network/virtualNetworks@2023-04-01' = {
  name: '${resourcePrefix}-vnet'
  location: location
  properties: {
    addressSpace: {
      addressPrefixes: [vnetAddressPrefix]
    }
    subnets: [
      {
        name: 'aks-subnet'
        properties: {
          addressPrefix: aksSubnetAddressPrefix
        }
      }
      {
        name: 'appgw-subnet'
        properties: {
          addressPrefix: appGwSubnetAddressPrefix
        }
      }
    ]
  }
}

// Reference to the AKS subnet
resource aksSubnet 'Microsoft.Network/virtualNetworks/subnets@2023-04-01' existing = {
  parent: vnet
  name: 'aks-subnet'
}

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
        count: 2
        vmSize: 'Standard_DS2_v2'
        osType: 'Linux'
        mode: 'System'
        vnetSubnetID: aksSubnet.id
      }
    ]
    networkProfile: {
      networkPlugin: 'azure'  // Use Azure CNI (not overlay)
      networkPolicy: 'azure'
      serviceCidr: '10.2.0.0/16'
      dnsServiceIP: '10.2.0.10'
    }
    // Enable workload identity and OIDC issuer
    oidcIssuerProfile: {
      enabled: true
    }
    securityProfile: {
      workloadIdentity: {
        enabled: true
      }
    }
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

// User-assigned managed identity for Kubernetes workload identity
resource podIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: podIdentityName
  location: location
}

// Outputs for resource names and endpoints
output aksClusterName string = aksCluster.name
output acrName string = acr.name
output openAiAccountName string = openAiAccount.name
output storageAccountName string = storageAccount.name
output storageAccountBlobEndpoint string = storageAccount.properties.primaryEndpoints.blob
output podIdentityName string = podIdentity.name
output podIdentityClientId string = podIdentity.properties.clientId
output podIdentityResourceId string = podIdentity.id
output vnetName string = vnet.name
output aksSubnetName string = 'aks-subnet'
output appGwSubnetName string = 'appgw-subnet'
output appGwSubnetAddressPrefix string = appGwSubnetAddressPrefix
