"""Write comparison outputs: results JSON, tag-review CSV (human spot check) and the markdown report."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from minicode.enrichment.prompts import JUDGE_CRITERIA
from minicode.enrichment.schema import PROMPT_VERSION
from minicode.evaluation.harness import TIE_MARGIN, WEIGHTS, Comparison, EvalItem

REVIEW_COLUMNS = [
    "item_id", "model", "raw_title", "has_transcript", "predicted_title", "predicted_topics", "predicted_content_type",
    "predicted_level", "predicted_presenter", "gold_topics", "gold_primary", "topic_f1", "judge_tag_relevance",
    "reviewer_topics_ok", "reviewer_correct_topics", "reviewer_level_ok", "reviewer_notes",
]


def write_review_csv(comparison: Comparison, items: list[EvalItem], path: Path) -> None:
    """One row per item x model. Reviewers fill the reviewer_* columns (y/n + corrected tags)."""
    by_id = {i.id: i for i in items}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:  # BOM so Excel opens UTF-8 correctly
        w = csv.DictWriter(f, fieldnames=REVIEW_COLUMNS)
        w.writeheader()
        for r in sorted(comparison.results, key=lambda r: (r.item_id, r.model)):
            item, out = by_id[r.item_id], r.output or {}
            w.writerow({
                "item_id": r.item_id, "model": r.model, "raw_title": item.input.raw_title,
                "has_transcript": "yes" if item.has_transcript else "no",
                "predicted_title": out.get("title", f"FAILED: {r.error}"),
                "predicted_topics": ";".join(out.get("topics", [])), "predicted_content_type": out.get("content_type", ""),
                "predicted_level": out.get("level", ""), "predicted_presenter": out.get("presenter") or "",
                "gold_topics": ";".join(item.gold.topics), "gold_primary": ";".join(item.gold.primary),
                "topic_f1": r.checks.get("topic_f1", ""),
                "judge_tag_relevance": (r.judge.get("scores") or {}).get("tag_relevance", ""),
                "reviewer_topics_ok": "", "reviewer_correct_topics": "", "reviewer_level_ok": "", "reviewer_notes": "",
            })


def write_results_json(comparison: Comparison, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(comparison.to_dict(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v * 100:.0f}%"


def render_report(comparison: Comparison, items: list[EvalItem], review_csv: str, results_json: str) -> str:
    s = comparison.summaries
    n_tx = sum(1 for i in items if i.has_transcript)
    lines = ["# Model comparison: enrichment LLM", ""]
    if comparison.mock:
        lines += [
            "> **MOCK RUN - not a model decision.** These numbers come from the deterministic mock LLMs",
            "> (`mock-a` = title-only heuristics, `mock-b` = title + transcript keywords) and a heuristic mock judge.",
            "> They prove the harness works end to end. Re-run with real keys (see *How to run* below) and",
            "> replace this file before picking Claude vs Azure OpenAI.",
            "",
        ]
    lines += [
        f"- Eval set: `{comparison.evalset}` ({len(items)} items: {n_tx} with transcripts, {len(items) - n_tx} title-only),"
        f" hash `{comparison.evalset_hash}`",
        f"- Candidates: {', '.join(f'`{x.client}`' for x in s)}; judge(s): {', '.join(f'`{j}`' for j in comparison.judges)}",
        f"- Prompt version: `{PROMPT_VERSION}`",
        "",
        "## Result",
        "",
        f"**Pick: `{comparison.pick}`** - {comparison.pick_reason}.",
        "",
        "| Model | Composite | Judge | Topic F1 | Topic precision | Primary-tag recall | Content type | Level ±100 | Presenter"
        " | Date ok | Clean title | 1st-try valid | Failures | Needs review |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for x in s:
        m = x.metrics
        lines.append(
            f"| `{x.client}` | **{x.composite:.3f}** | {_pct(x.judge)} | {_pct(m['topic_f1'])} | {_pct(m['topic_precision'])}"
            f" | {_pct(m['topic_recall'])} | {_pct(m['content_type'])} | {_pct(m['level'])} | {_pct(m['presenter'])}"
            f" | {_pct(m['date_ok'])} | {_pct(m['title_clean'])} | {_pct(m['first_try_valid'])} | {x.failures}"
            f" | {x.needs_review} |"
        )
    lines += [
        "",
        "| Model | With transcript | Title-only | Mean latency (s) | Input tokens | Output tokens | Est. cost |",
        "|---|---|---|---|---|---|---|",
    ]
    for x in s:
        cost = "n/a (pass --price)" if x.cost is None else f"${x.cost:.4f}"
        lines.append(f"| `{x.client}` | {x.with_transcript:.3f} | {x.title_only:.3f} | {x.mean_latency:.2f} | {x.input_tokens:,}"
                     f" | {x.output_tokens:,} | {cost} |")
    lines += ["", "Judge rubric means (1-5):", "", "| Model | " + " | ".join(JUDGE_CRITERIA) + " |",
              "|---|" + "---|" * len(JUDGE_CRITERIA)]
    for x in s:
        lines.append(f"| `{x.client}` | " + " | ".join(f"{x.judge_scores[c]:.2f}" for c in JUDGE_CRITERIA) + " |")

    lines += ["", "## Per item", "", "| Item | " + " | ".join(f"`{x.client}`" for x in s) + " |", "|---|" + "---|" * len(s)]
    by_key = {(r.item_id, r.model): r for r in comparison.results}
    model_names = {x.client: x.model for x in s}
    for item in items:
        cells = []
        for x in s:
            r = by_key.get((item.id, model_names[x.client]))
            if r is None or not r.ok:
                cells.append("FAILED")
                continue
            out = r.output or {}
            topics = ", ".join(out.get("topics", []))
            cells.append(f"{r.composite:.2f} - {topics} / {out.get('content_type')} / {out.get('level')}")
        tx = "" if item.has_transcript else " *(title only)*"
        lines.append(f"| `{item.id}`{tx} | " + " | ".join(cells) + " |")

    weights = ", ".join(f"{k} {v:.2f}" for k, v in WEIGHTS.items())
    lines += [
        "",
        "## Method",
        "",
        f"- **Composite** per item = weighted mean of: {weights}. Checks that do not apply (e.g. no gold presenter) are",
        "  dropped and the remaining weights re-normalized. A failed item (no valid output after retries) scores 0.",
        "- **Deterministic checks** against `data/eval/evalset.yaml` gold labels: topic precision (predicted tags inside the",
        "  acceptable set), primary-tag recall, F1, content type in the acceptable set, level within ±100, presenter match,",
        "  date equals the recording date (and none invented for title-only items), title follows `<Series>: <Topic>` with",
        "  no file artefacts, first attempt valid (schema + taxonomy) without retries.",
        "- **LLM-as-judge** scores accuracy, tag relevance, summary quality and title quality 1-5 against the source",
        "  (metadata + transcript) - see `minicode/enrichment/prompts.py`. Use two judges",
        "  (`--judge azure-openai,claude-foundry`) to dampen self-preference;",
        "  a judge never sees which model produced the candidate.",
        f"- **Pick rule**: highest composite wins if the margin is ≥ {TIE_MARGIN}; otherwise the cheaper model (with `--price`),",
        "  otherwise the faster one. The human tag spot check below can overrule the pick.",
        "",
        "## Human tag spot check",
        "",
        f"`{review_csv}` has one row per item × model. Reviewers fill `reviewer_topics_ok` (y/n),",
        "`reviewer_correct_topics` (`;`-separated tag ids if wrong), `reviewer_level_ok` and notes. Aim for ≥ 10 items per",
        "model; if reviewers reject > 20% of a model's tags, treat that as disqualifying regardless of the composite. Feed",
        "corrections back into the gold labels (`evalset.yaml`) and the taxonomy keywords.",
        "",
        "## How to run",
        "",
        "```powershell",
        "cd backend",
        "# mocks (this file):",
        "python -m minicode.evaluation --models mock-a,mock-b --judge mock",
        "# real models (AZURE_OPENAI_ENDPOINT + CLAUDE_FOUNDRY_ENDPOINT, `az login` or API keys;",
        "# see docs/week3-enrichment-search.md):",
        "python -m minicode.evaluation --models azure-openai,claude-foundry --judge azure-openai,claude-foundry `",
        "  --price azure-openai=0.40/1.60 --price claude-foundry=3/15",
        "```",
        "",
        f"Raw results: `{results_json}`.",
        "",
    ]
    return "\n".join(lines)


def write_report(comparison: Comparison, items: list[EvalItem], path: Path, review_csv: str, results_json: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(comparison, items, review_csv, results_json), encoding="utf-8")
