// Data-plane role assignments for the Function App managed identity (and AI Search MI).
param functionPrincipalId string
param searchPrincipalId string

param storageAccountName string
param keyVaultName string
param cosmosAccountName string
param searchServiceName string
param aiServicesName string

var roles = {
  storageBlobDataOwner: 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'
  storageBlobDataReader: '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'
  storageQueueDataContributor: '974c5e8b-45b9-4653-ba55-5f855dd0fb88'
  storageTableDataContributor: '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3'
  keyVaultSecretsUser: '4633458b-17de-408a-b874-0445c86b69e6'
  searchIndexDataContributor: '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
  searchServiceContributor: '7ca78c08-252a-4471-8644-bb5ff32d4ba0'
  cognitiveServicesOpenAIUser: '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
  cognitiveServicesSpeechUser: 'f2dc8367-1007-4938-bd23-fe263f013447'
  cosmosDataContributor: '00000000-0000-0000-0000-000000000002' // Cosmos DB built-in (data plane)
}

resource sa 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource kv 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' existing = {
  name: cosmosAccountName
}

resource search 'Microsoft.Search/searchServices@2024-06-01-preview' existing = {
  name: searchServiceName
}

resource ai 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: aiServicesName
}

var storageRoles = [
  roles.storageBlobDataOwner
  roles.storageQueueDataContributor
  roles.storageTableDataContributor
]

resource funcStorage 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for r in storageRoles: {
    name: guid(sa.id, functionPrincipalId, r)
    scope: sa
    properties: {
      principalId: functionPrincipalId
      principalType: 'ServicePrincipal'
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', r)
    }
  }
]

resource funcKv 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(kv.id, functionPrincipalId, roles.keyVaultSecretsUser)
  scope: kv
  properties: {
    principalId: functionPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.keyVaultSecretsUser)
  }
}

var searchRoles = [
  roles.searchIndexDataContributor
  roles.searchServiceContributor // create/update index definitions from code
]

resource funcSearch 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for r in searchRoles: {
    name: guid(search.id, functionPrincipalId, r)
    scope: search
    properties: {
      principalId: functionPrincipalId
      principalType: 'ServicePrincipal'
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', r)
    }
  }
]

var aiRoles = [
  roles.cognitiveServicesOpenAIUser
  roles.cognitiveServicesSpeechUser
]

resource funcAi 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for r in aiRoles: {
    name: guid(ai.id, functionPrincipalId, r)
    scope: ai
    properties: {
      principalId: functionPrincipalId
      principalType: 'ServicePrincipal'
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', r)
    }
  }
]

// AI Search integrated vectorization calls the embedding deployment with its own identity.
resource searchAi 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(ai.id, searchPrincipalId, roles.cognitiveServicesOpenAIUser)
  scope: ai
  properties: {
    principalId: searchPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.cognitiveServicesOpenAIUser)
  }
}

resource searchBlob 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(sa.id, searchPrincipalId, roles.storageBlobDataReader)
  scope: sa
  properties: {
    principalId: searchPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.storageBlobDataReader)
  }
}

resource funcCosmos 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-05-15' = {
  parent: cosmos
  name: guid(cosmos.id, functionPrincipalId, roles.cosmosDataContributor)
  properties: {
    principalId: functionPrincipalId
    roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/${roles.cosmosDataContributor}'
    scope: cosmos.id
  }
}
