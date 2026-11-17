# Week 1 checklist - human tasks

Code deliverables for week 1 are done (inventory, taxonomy, naming convention, IaC, pipelines). These items need people.

## 1. Portal team meeting (45 min)

**Goal:** agree scope and the integration contract for the Learning section.

Agenda:
1. (5 min) Goal and timeline - 4-5 week plan, demo of [inventory report](inventory-report.md).
2. (10 min) Where the Learning section lives in the portal: route, navigation, existing React/MSAL setup, design system/components we must reuse.
3. (10 min) Auth: does the portal already have an Entra SPA app registration we should reuse? Token audience for our API (`api://minicode-api-<env>/Learning.Read`)? Any APIM / gateway in front of portal APIs?
4. (10 min) Content decisions:
   - Confirm "all minicodes visible to all employees".
   - Scope: last 1 year only, or the full archive (titles go back to 2018)?
   - Show customer names (project intros)?
   - Review [tag taxonomy](taxonomy.md) and [naming convention](naming-convention.md).
5. (5 min) Hosting & ops: portal CI/CD, environments (dev/prod), who owns the Azure subscription and budget.
6. (5 min) Next steps and owners.

Decisions to record: portal integration approach, auth app regs, history scope, taxonomy sign-off, subscription/owner.

## 2. Graph `Sites.Selected` access request (to M365 / Entra admins)

> **Subject:** Request: read-only Graph access to the minicode Teams channel SharePoint site
>
> Hi,
>
> We are building a searchable "Learning" section in the company portal for our internal minicode recordings. The recordings and transcripts are stored in the SharePoint site behind the **minicode** Teams channel.
>
> We request:
> 1. An app registration `minicode-ingest-<dev|prod>` with Microsoft Graph **application** permission **`Sites.Selected`** (admin consent). `Sites.Selected` grants no access by itself.
> 2. A **read** grant for that app on the minicode site only:
>    ```http
>    POST https://graph.microsoft.com/v1.0/sites/{site-id}/permissions
>    {
>      "roles": ["read"],
>      "grantedToIdentities": [{ "application": { "id": "<app-client-id>", "displayName": "minicode-ingest" } }]
>    }
>    ```
>    (or `Grant-PnPAzureADAppSitePermission -AppId <id> -DisplayName minicode-ingest -Site <url> -Permissions Read`)
>
> The app will only read recordings (`.mp4`) and their metadata/transcripts from that site's document library; it does not write or access any other site. Credentials are a certificate in Azure Key Vault (or a managed-identity federated credential).
>
> Site URL: `<https://company.sharepoint.com/sites/...>`  -  Teams channel: `<team / minicode>`
>
> **Open question for you:** Teams meeting transcripts are not always stored as files in the channel site. If they are only available through the meeting (`/onlineMeetings/.../transcripts`), we would additionally need `OnlineMeetingTranscript.Read.All` with an application access policy restricted to the organizer accounts. Can you confirm where transcripts for channel meetings are stored in our tenant?
>
> Thanks!

Also ask for: the **site id** / drive id, and whether recordings have an **expiration policy** (Teams recordings expire by default - this explains the "expired" status in the inventory).

## 3. Legal / HR check: AI processing of presenter recordings

Questions to clear before running AI over recordings (week 3):

1. **Legal basis:** Is processing employees' voice, image and speech content with AI (transcription, summarization, tagging) covered by the existing legitimate-interest basis for internal knowledge sharing, or do we need consent/notice?
2. **Presenter information:** Do presenters need to be informed (privacy notice update, note in the minicode channel)? Can a presenter opt out or request removal of their recording from the Learning section?
3. **Presenter names as a facet:** OK to extract and display presenter names (search by presenter)?
4. **Former employees:** Can recordings by people who have left the company stay searchable? With their name?
5. **Data location & processors:** Azure OpenAI and Azure AI Speech in an EU region are fine? Is **Claude via Microsoft Foundry** acceptable (Anthropic model hosted by Microsoft; check data processing terms and region)?
6. **Retention:** Retention period for derived data (transcripts, summaries, embeddings) - same as the recording? Delete derived data when the recording is deleted/expires (the pipeline will support this)?
7. **Customer information:** Project intros may contain customer names/confidential details - is internal-only visibility enough, or should some be excluded?
8. **Works council / co-determination (yhteistoiminta):** does introducing AI processing of employee recordings require informing or negotiating with personnel representatives?
9. **DPIA:** Is a data protection impact assessment needed?

## 4. Other open items found in week 1

- [ ] Confirm the **source list**: the pasted list has a duplicated header row and 6 exact duplicate titles (see [inventory report](inventory-report.md)).
- [ ] Provide **dates** (or get Graph access) - the list has no dates but spans 2018-2026; scope is "last 1 year".
- [ ] Decide Cosmos DB (default) vs Azure SQL for metadata.
- [ ] Azure subscription + owner e-mail for budget alerts (`budgetContactEmails` in `infra/env/*.bicepparam`).
- [ ] Create the private GitHub repo, environments and OIDC credentials ([environments.md](environments.md)).
- [ ] Share the naming convention with presenters and ask them to enable **transcription** when recording.
