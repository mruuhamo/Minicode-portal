// Minicode Learning section - environment entry point (subscription scope).
// Deploy: az deployment sub create -l <region> -f infra/main.bicep -p infra/env/<env>.bicepparam
targetScope = 'subscription'

@allowed([
  'dev'
  'prod'
])
param environmentName string

param location string = 'swedencentral'

@description('Short workload name used in resource names.')
param workload string = 'minicode'

param tags object = {}

@description('Search SKU: basic for dev, standard if prod needs more storage/replicas.')
param searchSku string = 'basic'

@description('Azure OpenAI model deployments (see modules/ai.bicep).')
param aiDeployments array?

@description('Backend API app registration client ID (Entra ID). Leave empty until the app reg exists.')
param apiClientId string = ''

@description('SharePoint site ID of the minicode Teams channel (Graph). Leave empty until Sites.Selected is granted.')
param minicodeSiteId string = ''

@description('Folder of the channel recordings inside the site\'s default document library ("<Channel>/Recordings").')
param minicodeFolderPath string = 'General/Recordings'

@description('NCRONTAB schedule of the incremental ingestion timer (Graph delta + polling Speech jobs).')
param ingestionSchedule string = '0 0 * * * *'

@description('Primary Speech locale; language identification picks between the candidates.')
param speechLocale string = 'fi-FI'

@description('Monthly budget for the resource group. 0 = no budget.')
param monthlyBudget int = 0

param budgetContactEmails array = []

param budgetStartDate string = utcNow('yyyy-MM-01')

var namePrefix = '${workload}-${environmentName}'
// Globally unique names need a suffix; keep it stable per subscription + env.
var suffix = take(uniqueString(subscription().id, workload, environmentName), 6)
var allTags = union(tags, {
  workload: workload
  environment: environmentName
})

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${namePrefix}'
  location: location
  tags: allTags
}

module monitoring 'modules/monitoring.bicep' = {
  scope: rg
  name: 'monitoring'
  params: {
    location: location
    namePrefix: namePrefix
    tags: allTags
    retentionInDays: environmentName == 'prod' ? 90 : 30
  }
}

module keyVault 'modules/keyvault.bicep' = {
  scope: rg
  name: 'keyvault'
  params: {
    location: location
    name: 'kv-${workload}-${environmentName}-${suffix}'
    tags: allTags
    logAnalyticsId: monitoring.outputs.logAnalyticsId
    enablePurgeProtection: environmentName == 'prod'
  }
}

module storage 'modules/storage.bicep' = {
  scope: rg
  name: 'storage'
  params: {
    location: location
    name: take('st${workload}${environmentName}${suffix}', 24)
    tags: allTags
    skuName: environmentName == 'prod' ? 'Standard_ZRS' : 'Standard_LRS'
  }
}

module cosmos 'modules/cosmos.bicep' = {
  scope: rg
  name: 'cosmos'
  params: {
    location: location
    name: 'cosmos-${namePrefix}-${suffix}'
    tags: allTags
  }
}

module search 'modules/search.bicep' = {
  scope: rg
  name: 'search'
  params: {
    location: location
    name: 'srch-${namePrefix}-${suffix}'
    tags: allTags
    sku: searchSku
  }
}

module ai 'modules/ai.bicep' = {
  scope: rg
  name: 'ai'
  params: {
    location: location
    name: 'ais-${namePrefix}-${suffix}'
    tags: allTags
    deployments: aiDeployments
  }
}

module functionApp 'modules/functionapp.bicep' = {
  scope: rg
  name: 'functionapp'
  params: {
    location: location
    namePrefix: '${namePrefix}-${suffix}'
    tags: allTags
    storageAccountName: storage.outputs.name
    deploymentContainerUrl: storage.outputs.deploymentContainerUrl
    appInsightsConnectionString: monitoring.outputs.appInsightsConnectionString
    apiClientId: apiClientId
    appSettings: {
      MINICODE_ENVIRONMENT: environmentName
      MINICODE_SOURCE: empty(minicodeSiteId) ? 'mock' : 'graph'
      MINICODE_SITE_ID: minicodeSiteId
      MINICODE_FOLDER_PATH: minicodeFolderPath
      MINICODE_STORAGE: 'azure'
      MINICODE_SPEECH: 'auto'
      SPEECH_LOCALE: speechLocale
      SPEECH_CANDIDATE_LOCALES: 'fi-FI,en-US'
      BACKFILL_SCHEDULE: ingestionSchedule
      BACKFILL_LOOKBACK_DAYS: '365'
      INGESTION_ENABLED: 'true'
      KEY_VAULT_URI: keyVault.outputs.uri
      STORAGE_BLOB_ENDPOINT: storage.outputs.blobEndpoint
      COSMOS_ENDPOINT: cosmos.outputs.endpoint
      COSMOS_DATABASE: cosmos.outputs.databaseName
      COSMOS_CONTAINER: cosmos.outputs.containerName
      SEARCH_ENDPOINT: search.outputs.endpoint
      AI_SERVICES_ENDPOINT: ai.outputs.endpoint
    }
  }
}

module rbac 'modules/rbac.bicep' = {
  scope: rg
  name: 'rbac'
  params: {
    functionPrincipalId: functionApp.outputs.principalId
    searchPrincipalId: search.outputs.principalId
    storageAccountName: storage.outputs.name
    keyVaultName: keyVault.outputs.name
    cosmosAccountName: cosmos.outputs.name
    searchServiceName: search.outputs.name
    aiServicesName: ai.outputs.name
  }
}

module budget 'modules/budget.bicep' = if (monthlyBudget > 0 && !empty(budgetContactEmails)) {
  scope: rg
  name: 'budget'
  params: {
    name: 'budget-${namePrefix}'
    amount: monthlyBudget
    startDate: budgetStartDate
    contactEmails: budgetContactEmails
  }
}

output resourceGroupName string = rg.name
output functionAppName string = functionApp.outputs.name
output functionAppHostName string = functionApp.outputs.defaultHostName
output keyVaultName string = keyVault.outputs.name
output storageAccountName string = storage.outputs.name
output cosmosEndpoint string = cosmos.outputs.endpoint
output searchEndpoint string = search.outputs.endpoint
output aiServicesEndpoint string = ai.outputs.endpoint
