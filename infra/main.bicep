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

// ---------- Functions (Python on Linux, Consumption) ----------
resource plan 'Microsoft.Web/serverfarms@2022-09-01' = {
  name: '${functionAppName}-plan'
  location: location
  sku: {
    name: 'Y1'
    tier: 'Dynamic'
  }
  kind: 'functionapp'
  properties: {
    // Linux required for Python
    reserved: true
  }
}

resource func 'Microsoft.Web/sites@2022-09-01' = {
  name: functionAppName
  location: location
  kind: 'functionapp,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    httpsOnly: true
    serverFarmId: plan.id
    siteConfig: {
      linuxFxVersion: 'Python|3.11'
      ftpsState: 'Disabled'
      appSettings: [
        {
          name: 'FUNCTIONS_EXTENSION_VERSION'
          value: '~4'
        }
        {
          name: 'FUNCTIONS_WORKER_RUNTIME'
          value: 'python'
        }
        {
          name: 'SCM_DO_BUILD_DURING_DEPLOYMENT'
          value: '1'
        }
        {
          name: 'WEBSITE_RUN_FROM_PACKAGE'
          value: '1'
        }
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
output functionUrl string = 'https://${func.properties.defaultHostName}'


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

// ---------- Container Apps (Consumption, HTTP + Queue scaler; pulls from PUBLIC Docker Hub) ----------
@description('Container App name')
param containerAppName string

@description('Docker image on Docker Hub, e.g., docker.io/<user>/<repo>:<tag>')
param containerImage string

@description('Container port exposed by the app')
param containerPort int = 8000

@description('Expose a public HTTPS endpoint')
param exposePublic bool = true

@description('HTTP concurrency target per replica')
param httpConcurrentRequests int = 50

@description('Min replicas (0 enables scale to zero)')
param containerMinReplicas int = 0

@description('Max replicas')
param containerMaxReplicas int = 5

@description('Global cooldown before scaling in (seconds). 7200 = 2 hours.')
param cooldownSeconds int = 7200

@description('Scaler polling interval in seconds')
param pollingIntervalSeconds int = 30

@description('Non-secret env vars for the container: array of { name, value }')
param containerEnvPlain array = []

@secure()
@description('Secret map: name -> value. Secrets are created and also exposed via env using the same name.')
param containerSecretMap object = {}

// Convert secret map to Container Apps secrets + env refs
var containerSecretsArray = [for s in items(containerSecretMap): {
  name: s.key
  value: s.value
}]
var envFromSecrets = [for s in items(containerSecretMap): {
  name: s.key
  secretRef: s.key
}]

// Log Analytics for Container Apps logs
resource law 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: '${containerAppName}-law'
  location: location
  properties: {
    // SKU must be under properties for this API version
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
    // Optional features you can set on this API version include:
    // features: {
    //   disableLocalAuth: true
    //   enableDataExport: false
    //   enableLogAccessUsingOnlyResourcePermissions: true
    //   immediatePurgeDataOn30Days: false
    // }
  }
}

// Container Apps Environment (consumption)
resource cae 'Microsoft.App/managedEnvironments@2025-01-01' = {
  name: '${containerAppName}-env'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: law.properties.customerId
        sharedKey: listKeys(law.id, '2015-03-20').primarySharedKey
      }
    }
  }
}

// Container App pulling from PUBLIC Docker Hub (no registries block)
resource respondr 'Microsoft.App/containerApps@2025-01-01' = {
  name: containerAppName
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    environmentId: cae.id
    configuration: {
      activeRevisionsMode: 'Single'
      secrets: containerSecretsArray
      ingress: {
        external: exposePublic
        allowInsecure: false
        targetPort: containerPort
        transport: 'auto'
        traffic: [
          {
            latestRevision: true
            weight: 100
          }
        ]
      }
    }
    template: {
      containers: [
        {
          name: 'app'
          image: containerImage
          env: concat(
            containerEnvPlain,
            envFromSecrets,
            [
              { name: 'STORAGE_QUEUE_NAME', value: queueName }
              { name: 'AZURE_STORAGE_ACCOUNT', value: sa.name }
              { name: 'AZURE_OPENAI_ENDPOINT', value: 'https://${openai.name}.openai.azure.com/' }
            ]
          )
          probes: [
            {
              type: 'Liveness'
              httpGet: { path: '/health', port: containerPort }
              initialDelaySeconds: 10
              periodSeconds: 20
              timeoutSeconds: 5
              failureThreshold: 3
            }
          ]
          resources: { cpu: 1, memory: '2Gi' }
        }
      ]
      revisionSuffix: 'v1'
      scale: {
        minReplicas: containerMinReplicas
        maxReplicas: containerMaxReplicas
        pollingInterval: pollingIntervalSeconds
        cooldownPeriod: cooldownSeconds
        rules: [
          // HTTP autoscaling (concurrency)
          {
            name: 'http'
            http: {
              metadata: {
                concurrentRequests: string(httpConcurrentRequests)
              }
            }
          }
          // Azure Storage Queue autoscaling (managed identity)
          {
            name: 'queue'
            azureQueue: {
              identity: 'system'
              accountName: sa.name
              queueName: queueName
              queueLength: 1
            }
          }
        ]
      }
    }
  }
}

// RBAC: allow the Container App's managed identity to process queue messages
resource queueProcessorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(queue.id, containerAppName, 'queue-msg-processor')
  scope: queue
  properties: {
    // Storage Queue Data Message Processor
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '8a0f0c08-91a1-4084-bc3d-661d67233fed')
    principalId: respondr.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// Helpful output
output containerAppUrl string = exposePublic ? 'https://${respondr.properties.configuration.ingress.fqdn}' : ''
