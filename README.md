# Minicode Learning Section

Searchable learning library in the company portal for internal **minicode** recordings (Teams channel recordings stored in SharePoint/Stream). Recordings are ingested via Microsoft Graph, transcribed (Azure AI Speech when no transcript exists), enriched with an LLM (normalized title, summary, presenter, topic tags, level) and indexed in Azure AI Search for hybrid search with facets.

See [docs/architecture.md](docs/architecture.md) for the diagram and component map.

## Status

| Week | Theme | Status |
|---|---|---|
| 1 | Discovery & setup: inventory, taxonomy, naming convention, environments, CI/CD | ✅ code done - human tasks in [docs/week1-checklist.md](docs/week1-checklist.md) |
| 2 | Graph ingestion (backfill + change notifications), blob storage | - |
| 3 | Transcripts, chunking, LLM enrichment, embeddings, search index | - |
| 4 | Search API + React Learning section | - |

No real Azure / SharePoint access yet: the backend runs against **mock data** through the `RecordingSource` adapter; the Graph implementation plugs in later.

## Repository layout

```
backend/            Python Azure Functions app + minicode package
  minicode/
    naming.py         title normalizer (naming convention)
    taxonomy.py       taxonomy loader + keyword tagger
    inventory/        inventory pipeline, RecordingSource adapters (mock, Graph stub)
  tests/            pytest
  function_app.py   Functions entry point (/api/health)
data/
  recordings/titles.txt   existing minicode titles (227, raw export)
  taxonomy/taxonomy.yaml  tag taxonomy (source of truth)
docs/               inventory report, taxonomy, naming convention, architecture, environments, checklist
infra/              Bicep: main.bicep (subscription scope), modules/, env/{dev,prod}.bicepparam
frontend/           React + TypeScript Learning section (week 4)
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
