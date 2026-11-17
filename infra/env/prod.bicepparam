using '../main.bicep'

param environmentName = 'prod'
param location = 'swedencentral'
param searchSku = 'basic'
param tags = {
  costCenter: 'internal-portal'
  owner: 'portal-team'
}
param apiClientId = '' // TODO: backend API app registration (prod)
param minicodeSiteId = '' // TODO: after Sites.Selected grant
param monthlyBudget = 300
param budgetContactEmails = [] // TODO: add owner e-mail(s) to enable the budget
