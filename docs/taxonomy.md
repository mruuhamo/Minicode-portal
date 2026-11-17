# Tag taxonomy (draft v1)

Source of truth: [`data/taxonomy/taxonomy.yaml`](../data/taxonomy/taxonomy.yaml). Loader and keyword tagger: `backend/minicode/taxonomy.py`. Drafted from the 227 existing titles.

Three dimensions, which become AI Search facets:

| Dimension | Cardinality | Values |
|---|---|---|
| `topic` | 1-3 per recording | 17 tags (below) |
| `content_type` | exactly 1 | project-intro, training, conference-recap, case-study, demo, knowledge-share |
| `level` | exactly 1 | 100 Introductory, 200 Intermediate (default), 300 Advanced, 400 Expert |

Presenter and date are separate facets (metadata, not tags).

## Topics and coverage of current titles

Counts come from the week-1 keyword tagger (a title can have several topics).

| Tag id | Label | Titles |
|---|---|---|
| azure-platform | Azure platform & cloud infrastructure | 50 |
| ai-genai | AI, GenAI & machine learning | 45 |
| devops-iac | DevOps, CI/CD & infrastructure as code | 35 |
| data-analytics | Data, analytics & Microsoft Fabric | 31 |
| software-engineering | Software engineering & architecture | 31 |
| security-identity | Security, identity & compliance | 30 |
| customer-projects | Customer projects & project intros | 27 |
| ways-of-working | Agile, product & ways of working | 26 |
| internal-tooling | Zure internal tooling & templates | 24 |
| integration-api | Integration, messaging & APIs | 21 |
| conferences-events | Conferences & community events | 17 |
| testing-qa | Testing & quality assurance | 15 |
| ux-design | UX, design & accessibility | 15 |
| people-culture | People, HR & culture | 10 |
| iot-location | IoT, location & digital twins | 6 |
| monitoring-operations | Monitoring, observability & operations | 6 |
| general | Unclassified - needs manual review | 5 |

Every title gets at least one topic; `general` is used only as a fallback (tested in `backend/tests/test_taxonomy.py`). The five `general` titles (`PowerPoint Presentation`, `Minicode: Assets`, `Minicode: Exports`, `Meeting in "Minicode"`, and an untitled timestamp recording) need a human or the transcript to classify.

## How tagging works

- **Week 1 (now):** case-insensitive keyword rules in the YAML (`term` = whole word/phrase, `term*` = prefix). Good enough to validate the taxonomy and to seed the search index.
- **Week 3:** LLM enrichment reads the transcript and picks tags **only from this list** (ids are passed in the prompt; output is validated against the YAML). Keyword tags remain as a fallback and for evaluation.
- Level: an explicit `Level N` in the title or description wins; otherwise keywords (intro → 100, deep dive → 300, internals → 400); otherwise 200.

## Governance

- Tag ids are stable once the Learning section is live; labels can change freely.
- New tag: propose in the portal team channel when ≥ 5 recordings would use it; bump `version` in the YAML.
- Max ~20 topics - if a topic grows beyond ~60 recordings, consider splitting (e.g. `azure-platform`).
- Review the `general` bucket and LLM-suggested-but-unknown tags monthly.

## Open questions for the portal team

1. Is `customer-projects` OK to show to all employees (customer names in titles)?
2. Should `internal-tooling` be merged into `devops-iac`?
3. Do we want a `language` facet (fi/en)? Several recordings are in Finnish.
