// Curated recording metadata (normalized title, summary, presenter, tags, level, status).
param location string
param name string
param tags object = {}

param databaseName string = 'minicode'
param containerName string = 'recordings'

@description('Admin edit audit trail (one document per PATCH).')
param auditContainerName string = 'audit'

resource account 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' = {
  name: name
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: false
      }
    ]
    capabilities: [
      {
        name: 'EnableServerless'
      }
    ]
    disableLocalAuth: true // Entra ID (RBAC) only
    minimalTlsVersion: 'Tls12'
  }
}

resource db 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-05-15' = {
  parent: account
  name: databaseName
  properties: {
    resource: {
      id: databaseName
    }
  }
}

resource recordings 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  parent: db
  name: containerName
  properties: {
    resource: {
      id: containerName
      partitionKey: {
        paths: [
          '/sourceId'
        ]
        kind: 'Hash'
      }
    }
  }
}

resource audit 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  parent: db
  name: auditContainerName
  properties: {
    resource: {
      id: auditContainerName
      partitionKey: {
        paths: [
          '/recordingId'
        ]
        kind: 'Hash'
      }
    }
  }
}

output id string = account.id
output name string = account.name
output endpoint string = account.properties.documentEndpoint
output databaseName string = databaseName
output containerName string = containerName
output auditContainerName string = auditContainerName
