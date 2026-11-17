// Azure AI Services (Foundry) account: Azure OpenAI (embeddings + GPT), Speech (batch
// transcription for recordings without transcripts). Claude models are deployed from the
// Foundry model catalog (Marketplace terms) - see docs/environments.md; not managed here.
param location string
param name string
param tags object = {}

@description('Model deployments, e.g. [{ name, model, version, sku, capacity }]. Null = defaults below.')
param deployments array?

var defaultDeployments = [
  {
    name: 'text-embedding-3-large'
    model: 'text-embedding-3-large'
    version: '1'
    sku: 'Standard'
    capacity: 50
  }
  {
    name: 'gpt-4.1-mini'
    model: 'gpt-4.1-mini'
    version: '2025-04-14'
    sku: 'GlobalStandard'
    capacity: 50
  }
]

resource account 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: name
  location: location
  tags: tags
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    customSubDomainName: name
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

@batchSize(1) // deployments on the same account must be created sequentially
resource modelDeployments 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = [
  for d in deployments ?? defaultDeployments: {
    parent: account
    name: d.name
    sku: {
      name: d.sku
      capacity: d.capacity
    }
    properties: {
      model: {
        format: 'OpenAI'
        name: d.model
        version: d.version
      }
    }
  }
]

output id string = account.id
output name string = account.name
output endpoint string = account.properties.endpoint
