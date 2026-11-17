param location string
param name string
param tags object = {}

@allowed([
  'free'
  'basic'
  'standard'
])
@description('basic is enough for a few thousand chunks with vectors + semantic ranker.')
param sku string = 'basic'

@allowed([
  'disabled'
  'free'
  'standard'
])
param semanticSearch string = 'free'

resource search 'Microsoft.Search/searchServices@2024-06-01-preview' = {
  name: name
  location: location
  tags: tags
  sku: {
    name: sku
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'default'
    publicNetworkAccess: 'enabled'
    // Allow both keys (admin tooling) and Entra ID tokens (function app MI).
    authOptions: {
      aadOrApiKey: {
        aadAuthFailureMode: 'http401WithBearerChallenge'
      }
    }
    semanticSearch: sku == 'free' ? null : semanticSearch
  }
}

output id string = search.id
output name string = search.name
output endpoint string = 'https://${search.name}.search.windows.net'
output principalId string = search.identity.principalId
