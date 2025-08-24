param location string = resourceGroup().location
param saName string
param functionAppName string
param tableName string = 'ResponderMessages'
param queueName string = 'respondr-incoming'

resource sa 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: saName
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
  }
}

resource qsvc 'Microsoft.Storage/storageAccounts/queueServices@2023-01-01' = {
  name: 'default'
  parent: sa
}

resource queue 'Microsoft.Storage/storageAccounts/queueServices/queues@2023-01-01' = {
  name: queueName
  parent: qsvc
}

resource tsvc 'Microsoft.Storage/storageAccounts/tableServices@2023-01-01' = {
  name: 'default'
  parent: sa
}

resource table 'Microsoft.Storage/storageAccounts/tableServices/tables@2023-01-01' = {
  name: tableName
  parent: tsvc
}

// Use resource symbol reference and string interpolation to construct the connection string
var storageConn = 'DefaultEndpointsProtocol=https;AccountName=${sa.name};AccountKey=${sa.listKeys().keys[0].value};EndpointSuffix=${environment().suffixes.storage}'

resource plan 'Microsoft.Web/serverfarms@2022-09-01' = {
  name: '${functionAppName}-plan'
  location: location
  sku: {
    name: 'Y1'
    tier: 'Dynamic'
  }
}

resource func 'Microsoft.Web/sites@2022-09-01' = {
  name: functionAppName
  location: location
  kind: 'functionapp'
  properties: {
    serverFarmId: plan.id
    siteConfig: {
      appSettings: [
        {
          name: 'AzureWebJobsStorage'
          value: storageConn
        }
        {
          name: 'STORAGE_QUEUE_NAME'
          value: queueName
        }
      ]
    }
  }
}

output functionEndpoint string = func.properties.defaultHostName

// ---------- Azure OpenAI ----------
@description('Azure OpenAI account name (global unique, 2-64 chars, letters/numbers/hyphen).')
param openAiName string

@allowed([
  'Enabled'
  'Disabled'
])
param openAiPublicNetworkAccess string = 'Enabled'

@description('Azure region for the OpenAI account (must be an allowed AOAI region).')
param openAiLocation string = location

// Azure OpenAI account
resource openai 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: openAiName
  location: openAiLocation
  kind: 'OpenAI'
  sku: {
    name: 'S0'
  }
  properties: {
    publicNetworkAccess: openAiPublicNetworkAccess
    // customSubDomainName is optional; if omitted, endpoint = https://${name}.openai.azure.com/
  }
}

// Helpful outputs
output openAiEndpoint string = 'https://${openai.name}.openai.azure.com/'
