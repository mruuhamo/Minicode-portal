# Minicode Learning Section

Searchable learning library in the company portal for internal **minicode** recordings (Teams channel recordings stored in SharePoint/Stream). Recordings are ingested via Microsoft Graph, transcribed (Azure AI Speech when no transcript exists), enriched with an LLM (normalized title, summary, presenter, topic tags, level) and indexed in Azure AI Search for hybrid search with facets.

See [docs/architecture.md](docs/architecture.md) for the diagram and component map.

## Status

| Week | Theme | Status |
|---|---|---|
| 1 | Discovery & setup: inventory, taxonomy, naming convention, environments, CI/CD | ✅ code done - human tasks in [docs/week1-checklist.md](docs/week1-checklist.md) |
| 2 | Ingestion & transcripts: Graph backfill + delta, Speech batch transcription, VTT parsing, chunking | ✅ code done against mocks - see [docs/week2-ingestion.md](docs/week2-ingestion.md) |
| 3 | Enrichment & search: LLM enrichment, model comparison, embeddings, AI Search index, Search API (Entra) | ✅ code done against mocks - see [docs/week3-enrichment-search.md](docs/week3-enrichment-search.md) |
| 4 | Learning section: React listing/search/filters, detail page with video + jump-to-timestamp, MSAL, embeddable library | ✅ MVP demo against mocks - see [docs/week4-frontend.md](docs/week4-frontend.md) |

No real Azure / SharePoint access yet. The real Graph and Speech clients are implemented, but they run against an in-process **mock cloud** built from sample data (`MINICODE_SOURCE=mock`). Switching to the real services is configuration only.

## Repository layout

```
backend/            Python Azure Functions app + minicode package
  minicode/
    naming.py         title normalizer (naming convention)
    taxonomy.py       taxonomy loader + keyword tagger
    inventory/        inventory pipeline, RecordingSource adapters (mock, Graph)
    ingestion/        Graph + Speech clients, VTT parser, chunker, pipeline, state, mock cloud, CLI
    samples/          sample recordings/transcripts for the mock cloud
    enrichment/       LLM adapters (Azure OpenAI, Claude/Foundry, mock), schema validation, embeddings, catalogue repo, CLI
    search/           index schema, Azure AI Search + local hybrid backend, indexer
    api/              Search API routes, Entra JWT auth, local dev server
    evaluation/       Claude vs Azure OpenAI comparison harness (LLM-as-judge + deterministic checks)
    storage.py        blob storage abstraction (local filesystem, Azure Blob)
  tests/            pytest
  function_app.py   Functions entry point (/api/minicodes, /api/search, /api/manage/*, hourly ingest+enrich timer)
data/
  recordings/titles.txt   existing minicode titles (227, raw export)
  taxonomy/taxonomy.yaml  tag taxonomy (source of truth)
docs/               inventory report, taxonomy, naming convention, architecture, environments, checklist
infra/              Bicep: main.bicep (subscription scope), modules/, env/{dev,prod}.bicepparam
frontend/           Vite + React + TS Learning section: standalone app + embeddable library (week 4)
  src/                LearningSection, pages, components, typed API client, MSAL auth, video players
  public/demo/        demo video for the local mock-data player
.github/workflows/  ci.yml, infra.yml, deploy.yml
```

## Quickstart

```powershell
python -m venv .venv
.venv\Scripts\pip install -r backend\requirements-dev.txt
cd backend
..\.venv\Scripts\python -m pytest -q          # tests
..\.venv\Scripts\ruff check .                 # lint
..\.venv\Scripts\python -m minicode.inventory # regenerate docs/inventory-report.md + docs/inventory.csv
..\.venv\Scripts\python -m minicode.ingestion backfill --wait  # ingest mock recordings -> ..\out\blob
..\.venv\Scripts\python -m minicode.ingestion status
..\.venv\Scripts\python -m minicode.enrichment run          # enrich + index (mock LLM, local search)
$env:AUTH_MODE='dev'; ..\.venv\Scripts\python -m minicode.api serve  # Search API on :7071, dev auth bypass
..\.venv\Scripts\python -m minicode.evaluation              # model comparison -> docs/model-comparison.md
```

Frontend (Node 24; second terminal, with the API above running):

```powershell
cd frontend
npm ci
$env:VITE_PLAYER='html5'; $env:VITE_DEMO_VIDEO_URL='/demo/minicode-demo.mp4'; npm run dev   # http://localhost:5173
npm run lint; npm run typecheck; npm test; npm run build
```

Infra (needs Azure CLI with Bicep):

```powershell
az bicep build --file infra\main.bicep
az deployment sub what-if -l swedencentral -f infra\main.bicep -p infra\env\dev.bicepparam
```

## Week 1 deliverables

- [Recording inventory](docs/inventory-report.md) (+ [CSV](docs/inventory.csv))
- [Tag taxonomy](docs/taxonomy.md) / [taxonomy.yaml](data/taxonomy/taxonomy.yaml)
- [Naming convention](docs/naming-convention.md)
- [Environments, CI/CD & identity](docs/environments.md)
- [Human-task checklist](docs/week1-checklist.md)

## Week 2 deliverables

- [Ingestion & transcripts](docs/week2-ingestion.md): design, blob layout, state machine, local run, switching to real Graph/Speech, open questions

## Week 3 deliverables

- [Enrichment & search](docs/week3-enrichment-search.md): enrichment, index design, Search API + auth, local end-to-end demo, switching to real services, open questions
- [Model comparison report](docs/model-comparison.md) (mock run until keys exist) + [tag review sheet](docs/eval/tag-review.csv)

## Week 4 deliverables

- [Learning section](docs/week4-frontend.md): local full-stack demo, screenshots, portal integration contract, video player / Stream embed, accessibility, open questions
