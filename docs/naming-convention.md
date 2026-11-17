# Naming convention for minicode recordings

Applies to **new** recordings from now on. Existing recordings are not renamed in SharePoint; the pipeline stores a normalized display title alongside the original (see `backend/minicode/naming.py`).

## Format

```
<Series>: <Topic>[ - Part N]
```

| Rule | Do | Don't |
|---|---|---|
| Series prefix, exactly as listed below, followed by `: ` | `Minicode: Bicep modules` | `MiniCode -`, `Mini-Code`, `Minikode`, `[Minicode]_`, `Zure AI Minicode` |
| Topic in sentence case, English, 4-10 words | `Minicode: Durable Functions in production` | ALL CAPS, Finnish-only titles |
| Multi-part sessions end with ` - Part N` | `Minicode: The making of Zpeedy - Part 2` | `part 2/2`, `pt. 2`, `Part II`, `(2/3)` |
| **No** dates, timestamps or file suffixes | - | `-20221221_113315`, `14.1.2019`, `01/25` |
| **No** presenter names in the title | - | `Juval Nadav - ...`, `Join Jani as he presents ...` |
| No emoji, no escaped characters, single spaces | - | `🤖`, `\_`, double spaces |
| No markers like `(Optional)` / `[Mandatory]` in the title | - | `(Optional) [Minicode] ...` |

Date, presenter, level, mandatory flag and tags are **metadata**, not title text. Put them in the Teams meeting description (or a recording-sheet form) using this block, which the ingestion parses in week 2:

```
Presenter: Firstname Lastname
Level: 200
Tags: azure-platform, devops-iac
Mandatory: no
Language: en
```

The recording date comes from SharePoint/Graph (`createdDateTime`), never from the title.

## Series

| Series | Use for | Legacy variants mapped automatically |
|---|---|---|
| `Minicode` | Regular knowledge-share talk (default) | MiniCode, Mini-Code, Minikode, Minicode -, [Minicode], Zure AI Minicode, DeepData minicode, ZureOps Minicode, Surprise Minicode, Minicode (Nano Edition), no prefix |
| `Project Intro` | New customer project / PoC introduction | Project intro, PoC intro, `<customer> projekti-intro` |
| `Training` | Structured or mandatory training, guild trainings | Minitraining, `<X> Guild Training`, `... koulutus` |
| `AI Series` | Recurring "how I use AI" series | AI series |
| `People & Culture` | HR, wellbeing, culture talks | MiniHR, Miniculture, Minirant |

Guild trainings keep the guild as metadata (`guild: Security`): `Security Guild: HTTP Headers` becomes `Training: HTTP Headers`. Free-text notes such as `(Mandatory for tech roles, see description)` set `mandatory=true` but are left in the title by the normalizer; the week-3 LLM step removes them.

## Examples from the current library

| Original | Normalized | Extracted metadata |
|---|---|---|
| `(Optional) [Minicode]\_ Outbox pattern in ASP.NET Core application with CAP-20210827_100114` | `Minicode: Outbox pattern in ASP.NET Core application with CAP` | date 2021-08-27, optional |
| `Minicode  Blockchains and Azure - Friday, 14 December 2018 14.03.11` | `Minicode: Blockchains and Azure` | date 2018-12-14 |
| `IAM in Azure 14.1.2019` | `Minicode: IAM in Azure` | date 2019-01-14 |
| `Minicode: Zure Template BasicApp Updates 01/25` | `Minicode: Zure Template BasicApp Updates` | date 2025-01 |
| `Minicode: The making of Zpeedy - part 1: Just enough analysis` | `Minicode: The making of Zpeedy: Just enough analysis - Part 1` | part 1 |
| `🤖 Zure AI Minicode: Google NotebookLM and DeepSeek (run locally)` | `Minicode: Google NotebookLM and DeepSeek (run locally)` | - |
| `Minicode (Nano Edition): OpenWebUI` | `Minicode: OpenWebUI` | - |
| `MiniHR: stress & burnout` | `People & Culture: Stress & burnout` | - |
| `Juval Nadav - perjantai 7. syyskuuta 2018 15.09.03` | `Minicode: Untitled recording` | presenter Juval Nadav, date 2018-09-07 → **needs manual title** |

The full mapping for all 227 titles is in [`inventory.csv`](inventory.csv) (`normalized_title`, `presenter`, `date_hint`, `issues` columns).

## Normalizer

`normalize_title(raw) -> NormalizedTitle` (pure, idempotent, unit-tested against every existing title):

- `display` - `<Series>: <Topic>[ - Part N]`
- `series`, `series_inferred`, `title`, `part`, `presenter`, `date_hint`, `level_hint`, `guild`, `optional`, `mandatory`, `notes`
- `dedupe_key` - lowercase alphanumeric key for duplicate detection

The normalizer only cleans form. Translating Finnish titles, rewriting vague titles ("Assets", "Exports") and moving presenter names out of "Join X as..." titles is left to LLM enrichment in week 3, with this document as the instruction.

## Checklist for presenters (paste into the minicode channel)

1. Title: `Minicode: <topic>` (or Project Intro / Training / AI Series / People & Culture).
2. No date or your name in the title - they are captured automatically.
3. Fill the metadata block in the meeting description.
4. Turn on **transcription** when you start recording (needed for search; otherwise we pay for speech-to-text).
