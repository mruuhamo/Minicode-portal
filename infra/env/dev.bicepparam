using '../main.bicep'

param environmentName = 'dev'
param location = 'swedencentral'
param searchSku = 'basic'
param tags = {
  costCenter: 'internal-portal'
  owner: 'portal-team'
}
param apiClientId = '' // TODO: backend API app registration (dev)
param corsAllowedOrigins = ['http://localhost:5173'] // TODO: add the portal dev origin
param minicodeSiteId = '' // TODO: after Sites.Selected grant
param monthlyBudget = 150
param budgetContactEmails = [] // TODO: add owner e-mail(s) to enable the budget
