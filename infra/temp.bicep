
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

resource openAiAccount 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
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
  parent: openAiAccount
  name: gpt5nanoDeploymentName
  properties: {
    model: {
      name: 'gpt-5-nano'
      format: 'OpenAI'
      version: gpt5nanoModelVersion
    }
  }
  sku: {
    name: 'GlobalStandard'  // Changed from 'Standard' to 'GlobalStandard'
    capacity: 1
  }
}
