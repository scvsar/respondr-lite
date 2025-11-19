// Basic infrastructure parameters
param location string = resourceGroup().location
param saName string
param functionAppName string
param tableName string = 'ResponderMessages'
param queueName string = 'respondr-incoming'

// Azure OpenAI parameters
@description('Azure OpenAI account name (global unique, 2-64 chars, letters/numbers/hyphen).')
param openAiName string

@allowed([
  'Enabled'
  'Disabled'
])
param openAiPublicNetworkAccess string = 'Enabled'

@description('Azure region for the OpenAI account (must be an allowed AOAI region).')
param openAiLocation string = 'eastus2'

@description('Deployment name for the GPT-5-nano model.')
param gpt5nanoDeploymentName string = 'gpt-5-nano'

@description('Model version for GPT-5-nano. See model/version list in docs.')
param gpt5nanoModelVersion string = '2025-08-07'

@description('TPM units for GPT-5-nano deployment; 1 unit = 1,000 TPM. 200 units = 200,000 TPM.')
param gpt5nanoTpmUnits int = 200

// Container Apps parameters - matching the PowerShell script exactly
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

// Static Web App parameters
@description('Static Web App name')
param staticWebAppName string = ''

@description('Repository URL for Static Web App')
param repositoryUrl string = ''

@description('Repository branch for Static Web App')
param repositoryBranch string = 'main'

@description('Build preset for Static Web App (React, Angular, Vue, etc.)')
param appArtifactLocation string = 'frontend/build'

@description('API location for Static Web App integration')
param apiLocation string = ''

@description('GitHub token for Static Web App deployment')
@secure()
param githubToken string = ''

// EasyAuth parameters
@description('Enable Azure Entra ID authentication')
param enableAuth bool = false

@description('Azure AD Client ID for authentication')
param authClientId string = ''

@secure()
@description('Azure AD Client Secret for authentication')
param authClientSecret string = ''

@description('Azure AD Tenant ID (optional, defaults to current tenant)')
param authTenantId string = ''

resource openai 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: openAiName
  location: openAiLocation
  kind: 'OpenAI'
  sku: {
    name: 'S0'
  }
  properties: {
    publicNetworkAccess: openAiPublicNetworkAccess
  }
}

resource gpt5nanoDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: openai
  name: gpt5nanoDeploymentName
  properties: {
    model: {
      name: 'gpt-5-nano'
      format: 'OpenAI'
      version: gpt5nanoModelVersion
    }
  }
  sku: {
    name: 'GlobalStandard'
    capacity: gpt5nanoTpmUnits
  }
}

// ---------- Storage Account ----------
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

// ---------- Azure OpenAI (moved to top since it's referenced) ----------

// Convert secret map to Container Apps secrets + env refs, including auth secrets
var baseSecrets = [for s in items(containerSecretMap): {
  name: s.key
  value: s.value
}]

var authSecrets = enableAuth ? [
  {
    name: 'microsoft-provider-client-secret'
    value: authClientSecret
  }
] : []

var containerSecretsArray = union(baseSecrets, authSecrets)

var envFromSecrets = [for s in items(containerSecretMap): {
  name: s.key
  secretRef: s.key
}]

// Log Analytics for Container Apps logs
resource law 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: '${containerAppName}-law'
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
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
        sharedKey: law.listKeys().primarySharedKey
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
      revisionSuffix: 'v3'
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

// Container App Authentication Configuration (separate resource)
resource authConfig 'Microsoft.App/containerApps/authConfigs@2025-01-01' = if (enableAuth) {
  parent: respondr
  name: 'current'
  properties: {
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          clientId: authClientId
          clientSecretSettingName: 'microsoft-provider-client-secret'
          openIdIssuer: !empty(authTenantId) ? '${environment().authentication.loginEndpoint}${authTenantId}/v2.0' : '${environment().authentication.loginEndpoint}${tenant().tenantId}/v2.0'
        }
      }
    }
    globalValidation: {
      unauthenticatedClientAction: 'AllowAnonymous'
      redirectToProvider: 'azureActiveDirectory'
      excludedPaths: [
        '/'                          // Allow home page access
        '/.auth/*'                   // Auth endpoints
        '/api/auth/local/*'          // Local auth endpoints
        '/api/user'                  // User info endpoint
        '/static/*'                  // Static assets
        '/manifest.json'             // App manifest
        '/*.ico'                     // Icon files
        '/*.png'                     // Image files
        '/*.js'                      // JavaScript files
        '/*.css'                     // CSS files
        '/health'                    // Health check endpoint
      ]
    }
    platform: {
      enabled: true
      runtimeVersion: '~1'
    }
  }
}

// Azure Static Web App
resource staticWebApp 'Microsoft.Web/staticSites@2023-01-01' = if (!empty(staticWebAppName)) {
  name: staticWebAppName
  location: location
  sku: {
    name: 'Free'
    tier: 'Free'
  }
  properties: {
    repositoryUrl: repositoryUrl
    branch: repositoryBranch
    repositoryToken: githubToken
    buildProperties: {
      appLocation: '/frontend'
      appArtifactLocation: appArtifactLocation
      apiLocation: apiLocation
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

// RBAC: allow the Container App's managed identity to access Azure OpenAI
resource openaiRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(openai.id, containerAppName, 'openai-user')
  scope: openai
  properties: {
    // Cognitive Services OpenAI User
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')
    principalId: respondr.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// Outputs
output containerAppUrl string = exposePublic ? 'https://${respondr.properties.configuration.ingress.fqdn}' : ''
output openAiEndpoint string = 'https://${openai.name}.openai.azure.com/'
output gpt5nanoDeployment string = gpt5nanoDeploymentName
output staticWebAppName string = staticWebAppName
