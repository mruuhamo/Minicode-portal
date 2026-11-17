param location string

@description('Globally unique storage account name (3-24 lowercase alphanumerics).')
param name string

param tags object = {}

@allowed([
  'Standard_LRS'
  'Standard_ZRS'
  'Standard_GRS'
])
param skuName string = 'Standard_LRS'

@description('Blob containers for pipeline artifacts.')
param containers array = [
  'transcripts' // raw + normalized VTT/JSON transcripts
  'artifacts' // chunks, enrichment output, audio extracted for Speech
  'inventory' // backfill / delta snapshots
]

@description('Container used by the Flex Consumption function app for deployment packages.')
param deploymentContainerName string = 'app-package'

resource sa 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: name
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: {
    name: skuName
  }
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false // identity-based access only
    supportsHttpsTrafficOnly: true
    defaultToOAuthAuthentication: true
  }
}

resource blob 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: sa
  name: 'default'
  properties: {
    deleteRetentionPolicy: {
      enabled: true
      days: 7
    }
  }
}

resource dataContainers 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = [
  for c in union(containers, [deploymentContainerName]): {
    parent: blob
    name: c
    properties: {
      publicAccess: 'None'
    }
  }
]

output id string = sa.id
output name string = sa.name
output blobEndpoint string = sa.properties.primaryEndpoints.blob
output deploymentContainerUrl string = '${sa.properties.primaryEndpoints.blob}${deploymentContainerName}'
