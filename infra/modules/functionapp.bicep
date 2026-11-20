// Python Function App on Flex Consumption: ingestion (backfill, Graph change
// notifications / delta), transcript processing, enrichment and the Search API.
param location string
param namePrefix string
param tags object = {}

param storageAccountName string
param deploymentContainerUrl string
param appInsightsConnectionString string

@description('Extra app settings (endpoints etc.).')
param appSettings object = {}

param pythonVersion string = '3.12'
param maximumInstanceCount int = 40
param instanceMemoryMB int = 2048

@description('Entra ID app registration (backend API) client ID used for Easy Auth token validation. Empty = disabled.')
param apiClientId string = ''

@description('Browser origins allowed to call the API (portal / Learning section host).')
param corsAllowedOrigins array = []

resource plan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: 'asp-${namePrefix}'
  location: location
  tags: tags
  kind: 'functionapp'
  sku: {
    tier: 'FlexConsumption'
    name: 'FC1'
  }
  properties: {
    reserved: true
  }
}

var baseSettings = {
  AzureWebJobsStorage__accountName: storageAccountName
  AzureWebJobsStorage__credential: 'managedidentity'
  APPLICATIONINSIGHTS_CONNECTION_STRING: appInsightsConnectionString
  APPLICATIONINSIGHTS_AUTHENTICATION_STRING: 'Authorization=AAD'
}

resource site 'Microsoft.Web/sites@2024-04-01' = {
  name: 'func-${namePrefix}'
  location: location
  tags: tags
  kind: 'functionapp,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      minTlsVersion: '1.2'
      ftpsState: 'Disabled'
      cors: {
        allowedOrigins: corsAllowedOrigins
      }
    }
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: deploymentContainerUrl
          authentication: {
            type: 'SystemAssignedIdentity'
          }
        }
      }
      scaleAndConcurrency: {
        maximumInstanceCount: maximumInstanceCount
        instanceMemoryMB: instanceMemoryMB
      }
      runtime: {
        name: 'python'
        version: pythonVersion
      }
    }
  }
}

resource settings 'Microsoft.Web/sites/config@2024-04-01' = {
  parent: site
  name: 'appsettings'
  properties: union(baseSettings, appSettings)
}

// Easy Auth: require a valid Entra ID token for the API audience; /api/health stays open
// because unauthenticated requests are allowed through; the code validates the JWT itself (minicode/api/auth.py).
resource auth 'Microsoft.Web/sites/config@2024-04-01' = if (!empty(apiClientId)) {
  parent: site
  name: 'authsettingsV2'
  properties: {
    globalValidation: {
      requireAuthentication: false
      unauthenticatedClientAction: 'AllowAnonymous'
    }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          clientId: apiClientId
          openIdIssuer: '${environment().authentication.loginEndpoint}${subscription().tenantId}/v2.0'
        }
        validation: {
          allowedAudiences: [
            'api://${apiClientId}'
            apiClientId
          ]
        }
      }
    }
  }
}

output id string = site.id
output name string = site.name
output principalId string = site.identity.principalId
output defaultHostName string = site.properties.defaultHostName
