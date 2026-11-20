# Model comparison: enrichment LLM

> **MOCK RUN - not a model decision.** These numbers come from the deterministic mock LLMs
> (`mock-a` = title-only heuristics, `mock-b` = title + transcript keywords) and a heuristic mock judge.
> They prove the harness works end to end. Re-run with real keys (see *How to run* below) and
> replace this file before picking Claude vs Azure OpenAI.

- Eval set: `evalset.yaml` (20 items: 7 with transcripts, 13 title-only), hash `3263e550276c`
- Candidates: `mock-a`, `mock-b`; judge(s): `mock-b`
- Prompt version: `2026-11-v1`

## Result

**Pick: `mock-b`** - composite scores within 0.03 (0.007) and no clear cost/latency difference; provisional pick on composite - decide on cost, data residency and the human tag review.

| Model | Composite | Judge | Topic F1 | Topic precision | Primary-tag recall | Content type | Level ±100 | Presenter | Date ok | Clean title | 1st-try valid | Failures | Needs review |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `mock-a` | **0.849** | 68% | 90% | 89% | 95% | 100% | 100% | 100% | 100% | 100% | 100% | 0 | 0 |
| `mock-b` | **0.856** | 71% | 90% | 89% | 95% | 95% | 100% | 100% | 100% | 100% | 100% | 0 | 0 |

| Model | With transcript | Title-only | Mean latency (s) | Input tokens | Output tokens | Est. cost |
|---|---|---|---|---|---|---|
| `mock-a` | 0.904 | 0.819 | 0.00 | 4,047 | 2,019 | n/a (pass --price) |
| `mock-b` | 0.925 | 0.819 | 0.00 | 4,047 | 2,493 | n/a (pass --price) |

Judge rubric means (1-5):

| Model | accuracy | tag_relevance | summary_quality | title_quality |
|---|---|---|---|---|
| `mock-a` | 3.40 | 4.25 | 3.15 | 4.00 |
| `mock-b` | 3.75 | 4.30 | 3.30 | 4.00 |

## Per item

| Item | `mock-a` | `mock-b` |
|---|---|---|
| `bicep-private-registry` | 0.89 - devops-iac / knowledge-share / 200 | 0.86 - devops-iac, azure-platform / case-study / 200 |
| `transformer-architecture` | 0.88 - data-analytics, ai-genai, software-engineering / knowledge-share / 200 | 0.91 - ai-genai, data-analytics, software-engineering / knowledge-share / 200 |
| `threat-modeling` | 0.91 - security-identity / knowledge-share / 200 | 0.93 - security-identity / knowledge-share / 200 |
| `slo-monitoring` | 0.91 - monitoring-operations, customer-projects / knowledge-share / 200 | 0.96 - monitoring-operations, customer-projects / knowledge-share / 200 |
| `eu-ai-act` | 0.93 - ai-genai, security-identity / knowledge-share / 200 | 0.96 - ai-genai, security-identity / knowledge-share / 200 |
| `cd-for-sql` | 0.91 - devops-iac, data-analytics / knowledge-share / 200 | 0.96 - devops-iac, data-analytics / knowledge-share / 200 |
| `enterprise-ai-search` | 0.88 - ai-genai, ways-of-working, customer-projects / case-study / 200 | 0.91 - ai-genai, customer-projects, ways-of-working / case-study / 200 |
| `purview-101` *(title only)* | 0.83 - security-identity / knowledge-share / 200 | 0.83 - security-identity / knowledge-share / 200 |
| `axla-project-intro` *(title only)* | 0.85 - customer-projects / project-intro / 200 | 0.85 - customer-projects / project-intro / 200 |
| `fabric-conference-news` *(title only)* | 0.88 - data-analytics, conferences-events / conference-recap / 200 | 0.88 - data-analytics, conferences-events / conference-recap / 200 |
| `fluentassertions` *(title only)* | 0.83 - testing-qa / knowledge-share / 200 | 0.83 - testing-qa / knowledge-share / 200 |
| `subscriptions-management-groups` *(title only)* | 0.85 - azure-platform / knowledge-share / 200 | 0.85 - azure-platform / knowledge-share / 200 |
| `docker-containers` *(title only)* | 0.58 - devops-iac, ways-of-working / knowledge-share / 200 | 0.58 - devops-iac, ways-of-working / knowledge-share / 200 |
| `retrospectives` *(title only)* | 0.85 - ways-of-working / knowledge-share / 200 | 0.85 - ways-of-working / knowledge-share / 200 |
| `adhd-worklife` *(title only)* | 0.83 - people-culture / knowledge-share / 200 | 0.83 - people-culture / knowledge-share / 200 |
| `location-data-lessons` *(title only)* | 0.74 - data-analytics, iot-location, ways-of-working / case-study / 200 | 0.74 - data-analytics, iot-location, ways-of-working / case-study / 200 |
| `user-research-for-all` *(title only)* | 0.83 - ux-design / knowledge-share / 200 | 0.83 - ux-design / knowledge-share / 200 |
| `ghas-azure-devops` *(title only)* | 0.82 - azure-platform, devops-iac, security-identity / knowledge-share / 200 | 0.82 - azure-platform, devops-iac, security-identity / knowledge-share / 200 |
| `apim-appgw` *(title only)* | 0.85 - azure-platform, integration-api / knowledge-share / 200 | 0.85 - azure-platform, integration-api / knowledge-share / 200 |
| `ai-series-jani` *(title only)* | 0.89 - ai-genai, ways-of-working / knowledge-share / 200 | 0.89 - ai-genai, ways-of-working / knowledge-share / 200 |

## Method

- **Composite** per item = weighted mean of: judge 0.35, topic_f1 0.25, content_type 0.10, level 0.10, presenter 0.10, first_try_valid 0.10. Checks that do not apply (e.g. no gold presenter) are
  dropped and the remaining weights re-normalized. A failed item (no valid output after retries) scores 0.
- **Deterministic checks** against `data/eval/evalset.yaml` gold labels: topic precision (predicted tags inside the
  acceptable set), primary-tag recall, F1, content type in the acceptable set, level within ±100, presenter match,
  date equals the recording date (and none invented for title-only items), title follows `<Series>: <Topic>` with
  no file artefacts, first attempt valid (schema + taxonomy) without retries.
- **LLM-as-judge** scores accuracy, tag relevance, summary quality and title quality 1-5 against the source
  (metadata + transcript) - see `minicode/enrichment/prompts.py`. Use two judges
  (`--judge azure-openai,claude-foundry`) to dampen self-preference;
  a judge never sees which model produced the candidate.
- **Pick rule**: highest composite wins if the margin is ≥ 0.03; otherwise the cheaper model (with `--price`),
  otherwise the faster one. The human tag spot check below can overrule the pick.

## Human tag spot check

`docs/eval/tag-review.csv` has one row per item × model. Reviewers fill `reviewer_topics_ok` (y/n),
`reviewer_correct_topics` (`;`-separated tag ids if wrong), `reviewer_level_ok` and notes. Aim for ≥ 10 items per
model; if reviewers reject > 20% of a model's tags, treat that as disqualifying regardless of the composite. Feed
corrections back into the gold labels (`evalset.yaml`) and the taxonomy keywords.

## How to run

```powershell
cd backend
# mocks (this file):
python -m minicode.evaluation --models mock-a,mock-b --judge mock
# real models (AZURE_OPENAI_ENDPOINT + CLAUDE_FOUNDRY_ENDPOINT, `az login` or API keys;
# see docs/week3-enrichment-search.md):
python -m minicode.evaluation --models azure-openai,claude-foundry --judge azure-openai,claude-foundry `
  --price azure-openai=0.40/1.60 --price claude-foundry=3/15
```

Raw results: `docs/eval/results.json`.
