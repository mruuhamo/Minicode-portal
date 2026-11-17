# Environments, CI/CD and identity

## Environments

| | dev | prod |
|---|---|---|
| Resource group | `rg-minicode-dev` | `rg-minicode-prod` |
| Params | [`infra/env/dev.bicepparam`](../infra/env/dev.bicepparam) | [`infra/env/prod.bicepparam`](../infra/env/prod.bicepparam) |
| Storage redundancy | LRS | ZRS |
| Log retention | 30 days | 90 days |
| Key Vault purge protection | off | on |
| Budget (alerts at 80 % actual / 100 % forecast) | 150 / month | 300 / month |
| Data source | mock until `minicodeSiteId` is set | Graph |

Region defaults to `swedencentral` (AI Services, Flex Consumption and AI Search all available). Change `location` in the param files if the company requires another EU region.

### Resources (`infra/main.bicep`, subscription scope)

| Module | Resources |
|---|---|
| `monitoring` | Log Analytics workspace, Application Insights (Entra auth only) |
| `keyvault` | Key Vault (RBAC mode, audit logs to Log Analytics) |
| `storage` | Storage account (no shared keys) + containers `transcripts`, `artifacts`, `inventory`, `app-package` |
| `cosmos` | Cosmos DB serverless, db `minicode`, container `recordings` (pk `/sourceId`), local auth disabled |
| `search` | Azure AI Search (`basic`, semantic ranker free tier, system identity) |
| `ai` | Azure AI Services (Foundry) account: `text-embedding-3-large`, `gpt-4.1-mini`; Speech via same account |
| `functionapp` | Flex Consumption plan + Python 3.12 Function App, system identity, optional Easy Auth (Entra) |
| `rbac` | Function MI → Storage blob/queue/table, Key Vault secrets user, Search index + service contributor, OpenAI + Speech user, Cosmos data contributor. Search MI → OpenAI user, blob reader |
| `budget` | Monthly consumption budget (only when `budgetContactEmails` is set) |

**Claude via Microsoft Foundry** is not in Bicep: Anthropic models are deployed from the Foundry model catalog (Marketplace subscription + terms acceptance) into the same AI Services account. Do it once per environment in the portal and record the deployment name in the app settings (week 3).

### Validate / deploy locally

```powershell
az bicep build --file infra/main.bicep
az bicep build-params --file infra/env/dev.bicepparam
az deployment sub what-if -l swedencentral -f infra/main.bicep -p infra/env/dev.bicepparam
az deployment sub create  -l swedencentral -f infra/main.bicep -p infra/env/dev.bicepparam
```

## GitHub Actions

| Workflow | Trigger | Needs Azure? |
|---|---|---|
| [`ci.yml`](../.github/workflows/ci.yml) | push to main, PRs | No - ruff, pytest, checks `docs/inventory-*` is regenerated |
| [`infra.yml`](../.github/workflows/infra.yml) | changes under `infra/` | Build/lint: no. What-if: yes, only when repo variable `AZURE_WHATIF_ENABLED=true` |
| [`deploy.yml`](../.github/workflows/deploy.yml) | manual (`environment`: dev/prod) | Yes - Bicep deploy, Functions deploy (remote build), `/api/health` smoke test |

### One-time setup (after the private repo exists)

1. Create GitHub environments `dev` and `prod` (add required reviewers on `prod`).
2. Create an Entra app registration (or user-assigned managed identity) per environment, e.g. `gh-minicode-dev`.
3. Add a **federated credential**: issuer `https://token.actions.githubusercontent.com`, subject `repo:<org>/<repo>:environment:dev` (and `:prod` for the prod identity).
4. Grant it **Contributor** + **User Access Administrator** (constrained to the roles in `rbac.bicep`, or **Role Based Access Control Administrator** with a condition) on the subscription - the template creates the resource group and role assignments.
5. Add environment **secrets**:

   | Secret | Value |
   |---|---|
   | `AZURE_CLIENT_ID` | app registration / MI client id |
   | `AZURE_TENANT_ID` | tenant id |
   | `AZURE_SUBSCRIPTION_ID` | target subscription |

6. Optional repository **variables**: `AZURE_LOCATION` (default `swedencentral`), `AZURE_WHATIF_ENABLED=true`.

## Entra ID app registrations (manual, week 1-2)

| App | Purpose | Settings |
|---|---|---|
| `minicode-api-<env>` | Backend API audience | Expose API `api://<clientId>`, scope `Learning.Read`; client id goes to `apiClientId` param (enables Easy Auth on the Function App) |
| `minicode-spa-<env>` | React Learning section (MSAL) | SPA redirect URIs of the portal; delegated permission `Learning.Read` on the API app; admin consent |
| `minicode-ingest-<env>` | Graph access for ingestion | **Application** permission `Sites.Selected` (admin consent) + per-site `read` grant; credential = certificate in Key Vault, or federated credential to the Function App's managed identity |

See [week1-checklist.md](week1-checklist.md) for the Sites.Selected request text.

Ingestion settings (`MINICODE_*`, `SPEECH_*`, `BACKFILL_*`, `INGESTION_ENABLED`) are listed in [week2-ingestion.md](week2-ingestion.md#settings). The Bicep parameters for them are `minicodeSiteId`, `minicodeFolderPath`, `ingestionSchedule` and `speechLocale`.
