# Week 3 - Enrichment & search

Deliverable: a tagged, searchable minicode index plus the Search API (MVP backend demo). Everything runs locally against
mocks (mock LLM, hash embeddings, local catalogue, local hybrid search, dev auth). The real clients (Azure OpenAI, Claude on
Microsoft Foundry, Azure OpenAI embeddings, Cosmos DB, Azure AI Search, Entra ID JWT validation) are implemented behind the
same interfaces. Switching to them is configuration only.

```
ingest (week 2)          enrich                                  index                         query
chunks/<id>.json  --->   EnrichmentInput -> LLM -> validate  --> summary doc + chunk docs  --> Search API
recordings/<id>.json     (retry with errors, taxonomy only)      + embeddings (cached)         GET /api/search ...
                         -> catalogue (Cosmos / local JSON)      -> AI Search / local index
```

## Components

| Concern | Interface | Implementations | Code |
|---|---|---|---|
| LLM | `LLMClient.complete(messages, schema, name)` | `AzureOpenAIChat` (openai SDK, Entra token or key, strict `json_schema`), `ClaudeFoundryChat` (Foundry `/anthropic/v1/messages`, forced tool use), `MockLLM` (deterministic, profiles `mock-a` / `mock-b`) | `minicode/enrichment/llm.py` |
| Validation | `validate(data)` | JSON schema + taxonomy constraints. Unknown tags are dropped when valid ones remain, otherwise the model retries with the error list (max 3 attempts). The keyword tagger is the fallback. | `enrichment/schema.py`, `enricher.py` |
| Catalogue | `CatalogRepository` | `CosmosRepository` (Entra auth, `recordings` + `audit` containers), `LocalJsonRepository`, `InMemoryRepository` | `enrichment/repository.py` |
| Embeddings | `Embedder.embed(texts)` | `AzureOpenAIEmbedder` (text-embedding-3-large @ 1024 dims), `HashEmbedder` (deterministic, local) | `enrichment/embeddings.py` |
| Search | `SearchBackend` | `AzureSearchBackend` (REST 2024-07-01, Entra or key), `LocalSearchBackend` (BM25 + cosine, RRF fusion, facets, OData-equivalent filters, highlights) | `search/` |
| API | `Api.handle(ApiRequest)` | Azure Functions (`function_app.py`) and a local dev server (`python -m minicode.api serve`) | `api/routes.py` |
| Auth | `Authenticator.require(headers, admin)` | `EntraAuthenticator` (RS256 via JWKS, issuer v1/v2, audience `api://<id>` or `<id>`, tenant, exp/nbf), `DevAuthenticator` | `api/auth.py` |

### Enrichment output

The fields are normalized `title` (following the [naming convention](naming-convention.md)), `summary` (2-4 sentences),
`presenter`, `date`, `topics` (1-4 tags from [taxonomy.yaml](../data/taxonomy/taxonomy.yaml), primary first), `contentType`,
`level` (100-400), `keywords`, `language` and `confidence`. Low confidence (< 0.5), a retry or a fallback all set
`needsReview`.

Each catalogue document keeps four layers:

- `llm`: the last validated output.
- `enrichment`: model, prompt version, input hash, attempts.
- `overrides`: admin corrections.
- the effective fields that the API and the index show.

**Admin overrides always win.** Re-enrichment (also with `--force`) rewrites `llm` but never `overrides`. If you PATCH a
field to `null`, it reverts to the LLM value. Re-enrichment is skipped while the input hash (transcript chunks + metadata +
prompt version + model) is unchanged.

### Index design

There are two indexes. The prefix comes from `SEARCH_INDEX_PREFIX`, default `minicode`. See `search/schema.py`.

- `<prefix>-recordings`: one document per minicode, used for browse/list, facets and sorting by date.
- `<prefix>-chunks`: one `summary` document plus one document per transcript chunk. Every chunk document copies the parent
  fields: title, summary, topics, contentType, level, presenter, date, year, language, webUrl, hidden.
  - Filterable/facetable: `topics`, `contentType`, `level`, `presenter`, `language`, `year`. `date` is filterable and sortable.
  - `contentVector`: 1024 dims, HNSW cosine. Semantic configuration `minicode-semantic`: title, content + summary, topics +
    keywords.
  - `start` / `end` / `speakers` give each hit its timestamp, so the UI can jump to it.

A search runs hybrid (BM25 + vector, plus the semantic ranker when `SEMANTIC_RANKER=true`) over the chunk index, takes the
top 200 hits and groups them by recording. Each recording returns up to 3 highlighted chunk hits with `startLabel`
(`mm:ss`) and a Stream URL at that position. Facets for a text search are counted over the grouped recordings. With an empty
query the API lists recordings from the recordings index.

## Search API

All routes sit under `/api`. Every route needs a valid Entra access token for the backend API app registration, with the
`Learning.Read` delegated scope or the `Learning.Read` / `Learning.Admin` app role. `manage/*` routes need the
`Learning.Admin` app role.

| Method & route | Purpose |
|---|---|
| `GET /api/minicodes?tags=&contentType=&level=&presenter=&language=&from=&to=&sort=date\|+date\|title\|level&top=&skip=` | Browse with filters, paging and facets. Tags within a facet are OR'ed; facets are AND'ed. |
| `GET /api/minicodes/{id}` | Detail view with chapters (chunk timestamps + URLs) |
| `GET /api/search?q=&tags=&presenter=&from=&to=&top=&skip=` | Hybrid search with facets and highlighted chunk hits with timestamps |
| `GET /api/taxonomy` | Tag lists for the UI filters |
| `GET /api/manage/minicodes/{id}` | Admin view: raw title, LLM output, overrides, audit |
| `PATCH /api/manage/minicodes/{id}` | Correct `title`, `summary`, `presenter`, `date`, `topics`, `keywords`, `contentType`, `level` or `hidden`. The change is validated against the taxonomy, audited and pushed to the index without re-embedding. |
| `POST /api/manage/enrich` `{"force": false, "ids": [...]}` | Enrich, then index the changed recordings |
| `POST /api/manage/reindex` | Rebuild both indexes from the catalogue |
| `POST /api/manage/ingest?mode=backfill\|incremental` | Week 2 ingestion. Function-key protected. |

> **Route change:** the brief asked for `/api/admin/...`, but Azure Functions reserves the `admin` route prefix for its host
> API, so admin routes live under `/api/manage/...`. Week 2's `/api/admin/ingest` is now `/api/manage/ingest`.

Errors are returned as `{"error": "..."}`:

- 400: bad filter, unknown tag, bad paging or invalid PATCH.
- 401: missing or invalid token, with a `WWW-Authenticate` header.
- 403: missing role or scope.
- 404: not found.
- 405: wrong method.
- 503: index not built yet.

**Dev bypass:** `AUTH_MODE=dev` skips token validation and returns a fixed admin principal. Send `X-Dev-Roles: none` to act
as a plain reader. Dev mode is logged as a warning and **refused at startup when `MINICODE_ENVIRONMENT=prod`**. Bicep always
deploys `AUTH_MODE=entra`.

## Run the demo locally (end to end)

```powershell
cd backend
$env:MINICODE_DATA_DIR = "$PWD\..\out"   # default anyway; everything goes to out\blob, out\catalog, out\search
$env:AUTH_MODE = "dev"

# 1. ingest (week 2): 7 mock minicodes, 4 Teams VTT + 3 via the mock Speech path
..\.venv\Scripts\python -m minicode.ingestion backfill --wait

# 2. enrich + index (mock LLM, hash embeddings, local catalogue + search)
..\.venv\Scripts\python -m minicode.enrichment run
..\.venv\Scripts\python -m minicode.enrichment search "bicep registry"
..\.venv\Scripts\python -m minicode.enrichment show <id>

# 3. API on http://localhost:7071 (or `func start` with local.settings.json)
..\.venv\Scripts\python -m minicode.api serve
```

```powershell
curl "http://localhost:7071/api/search?q=threat%20modeling&top=3"
curl "http://localhost:7071/api/minicodes?tags=ai-genai&from=2026-01-01"
curl "http://localhost:7071/api/minicodes/<id>"
curl -X PATCH "http://localhost:7071/api/manage/minicodes/<id>" -H "Content-Type: application/json" `
     -d '{\"title\": \"Minicode: Bicep registries in practice\", \"topics\": [\"devops-iac\"]}'
curl -X PATCH "http://localhost:7071/api/manage/minicodes/<id>" -H "X-Dev-Roles: none" -d '{}'   # 403
```

Set `CORS_ORIGIN=http://localhost:5173` for the week 4 SPA dev server.

## Switching to real services

Set these app settings (Bicep sets them in Azure, see `infra/main.bicep`):

| Setting | Value |
|---|---|
| `LLM_PROVIDER` | `azure-openai[:deployment]` or `claude-foundry[:deployment]`, the model you pick below |
| `AI_SERVICES_ENDPOINT` / `AZURE_OPENAI_ENDPOINT` | `https://<ais>.cognitiveservices.azure.com/` |
| `AZURE_OPENAI_CHAT_DEPLOYMENT`, `AZURE_OPENAI_EMBEDDING_DEPLOYMENT` | `gpt-4.1-mini`, `text-embedding-3-large` |
| `CLAUDE_FOUNDRY_ENDPOINT`, `CLAUDE_DEPLOYMENT` | Foundry resource endpoint and Claude deployment name (deployed from the Foundry model catalog, not Bicep) |
| `EMBEDDINGS_PROVIDER=azure-openai`, `EMBEDDING_DIMENSIONS=1024` | Changing dimensions requires an index rebuild |
| `MINICODE_REPOSITORY=cosmos`, `COSMOS_ENDPOINT`, `COSMOS_DATABASE`, `COSMOS_CONTAINER`, `COSMOS_AUDIT_CONTAINER` | Serverless account, Entra-only |
| `SEARCH_BACKEND=azure`, `SEARCH_ENDPOINT`, `SEARCH_INDEX_PREFIX`, `SEMANTIC_RANKER` | Indexes are created/updated from code (`ensure_indexes`) |
| `AUTH_MODE=entra`, `AUTH_TENANT_ID`, `API_CLIENT_ID` | Backend API app registration; expose `Learning.Read` scope + `Learning.Admin` app role |

Locally, use `az login`: `DefaultAzureCredential` picks up your account, so you need the same data-plane roles as the
Function App MI (see `infra/modules/rbac.bicep`). For quick experiments, `AZURE_OPENAI_API_KEY` / `CLAUDE_API_KEY` also work
(AI Search is Entra-only). Never set keys in Azure.

## Model comparison (Claude vs Azure OpenAI)

The harness is `python -m minicode.evaluation`. The eval set is [data/eval/evalset.yaml](../data/eval/evalset.yaml): 20
items, made of 7 sample minicodes with transcripts and 13 inventory titles that have only a title. Each item has
hand-written gold labels (primary topic, topics, content type, level, presenter). **The gold labels are a draft. Review them
before trusting the numbers.**

Scoring per item:

- Deterministic checks: topic precision/recall/F1, content type, level (±100 counts as half), presenter, date, title shape,
  valid on the first try.
- LLM-as-judge: accuracy, tag relevance, summary quality and title quality, each on a 1-5 scale. The judge sees the source
  and the candidate, never the model name.
- Composite: a weighted mean, re-normalized when a check does not apply. A failure scores 0.

Pick rule:

1. The higher composite wins outright if the margin is ≥ 0.03.
2. Otherwise the cheaper model wins (`--price`).
3. Otherwise the faster one wins.
4. Otherwise it is a provisional pick, and the human tag review and data residency decide.

```powershell
# mocks (CI-safe; regenerates docs/model-comparison.md, docs/eval/tag-review.csv, docs/eval/results.json)
..\.venv\Scripts\python -m minicode.evaluation

# real: smoke-test 3 items first, then the full set with two judges (dampens self-preference) and list prices
$env:AI_SERVICES_ENDPOINT = "https://<ais>.cognitiveservices.azure.com/"
$env:CLAUDE_FOUNDRY_ENDPOINT = "https://<foundry>.services.ai.azure.com/"
..\.venv\Scripts\python -m minicode.evaluation --models azure-openai,claude-foundry --judge azure-openai,claude-foundry --limit 3
..\.venv\Scripts\python -m minicode.evaluation --models azure-openai:gpt-4.1-mini,claude-foundry:claude-sonnet-4-6 `
    --judge azure-openai:gpt-4.1,claude-foundry --price azure-openai:gpt-4.1-mini=0.4/1.6 --price claude-foundry:claude-sonnet-4-6=3/15
```

The current [docs/model-comparison.md](model-comparison.md) is a **mock run**. It proves that the pipeline works; it is not a
model decision.

### Human tag review (spot check)

1. Open `docs/eval/tag-review.csv` in Excel. It is UTF-8 with BOM and has one row per item × model.
2. Fill in `reviewer_topics_ok`, `reviewer_level_ok` and `reviewer_summary_ok` (y/n), plus `reviewer_notes`.
3. Use at least 2 reviewers on about 10 rows each, including the Finnish titles.
4. If the reviewers reject the tags of the "winning" model notably more often, that overrules the composite.
5. Recurring tag misses are fed back into `taxonomy.yaml` descriptions or keywords. The prompt includes the descriptions.

Record the decision (model, date, reason) at the top of `docs/model-comparison.md` and set `llmProvider` in
`infra/env/*.bicepparam`.

## Infra changes

- Cosmos: new `audit` container (pk `/recordingId`). `recordings` keeps pk `/sourceId`.
- Search: `semanticSearch` (free plan by default) and `searchIndexPrefix` parameters.
- Function App settings for everything above, plus `ENRICHMENT_ENABLED`. The hourly timer runs ingest → enrich → index.
- RBAC already granted the roles that week 3 needs:
  - Cosmos DB Built-in Data Contributor.
  - Search Index Data Contributor and Search Service Contributor (the code creates the index definitions).
  - Cognitive Services OpenAI User.
- Claude deployment: deploy it from the Foundry model catalog (Marketplace terms), then set `claudeFoundryEndpoint` /
  `claudeDeployment`.

## Open questions

1. **Summary language**: English for all, or the recording's language (Finnish recordings get Finnish summaries)? The default
   is English (`SUMMARY_LANGUAGE`).
2. **Read access**: the API requires the `Learning.Read` scope, which every SPA user gets through consent. Should "any
   signed-in employee" instead be enforced by tenant only, or through an assignment-required app registration?
3. **Stream timestamp links**: `?nav=` (base64 `playbackOptions.startTimeInSeconds`) is unverified against our tenant.
   Check it with one real recording.
4. **Mixed Finnish/English analyzer**: one `standard.lucene` analyzer for both languages, since there is no Finnish stemming
   in a mixed field. Vectors cover recall. Revisit this if Finnish keyword search feels weak.
5. **Facet counts for text search** are computed over the top 200 chunk hits, grouped. That is fine at our scale, but it is
   not exact.
6. **Claude availability in swedencentral** (or the closest EU region) and the data-processing terms. This is part of the
   legal/HR check.
7. **The mock judge is also candidate mock-b** (self-preference). Real runs should use two judges, as above.
8. **The gold labels in the eval set** need human review.
9. Week 2 items still open: the sidecar `.vtt` assumption, the Speech request shape, ffmpeg on Flex Consumption, the
   recordings folder path, and expiry detection. See [week2-ingestion.md](week2-ingestion.md#open-questions--to-verify-with-real-access).
