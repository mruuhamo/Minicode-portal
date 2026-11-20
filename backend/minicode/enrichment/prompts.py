"""Prompts for enrichment and for the LLM-as-judge used by the model comparison."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

import yaml

from minicode.enrichment.inputs import EnrichmentInput
from minicode.naming import SERIES_LABELS
from minicode.paths import TAXONOMY_FILE

LEVEL_GUIDE = {
    100: "introductory overview, no prior knowledge needed",
    200: "intermediate: practical how-to for practitioners",
    300: "advanced: assumes hands-on experience, design trade-offs",
    400: "expert: internals, deep dives, edge cases",
}

Message = dict[str, str]


@lru_cache(maxsize=1)
def _taxonomy_text() -> str:
    raw = yaml.safe_load(TAXONOMY_FILE.read_text(encoding="utf-8"))
    lines = []
    for dim_id in ("topic", "content_type"):
        lines.append(f"{dim_id} tags (use the id):")
        for t in raw["dimensions"][dim_id]["tags"]:
            hints = ", ".join(str(k).rstrip("*") for k in (t.get("keywords") or [])[:8])
            lines.append(f"- {t['id']}: {t['label']}" + (f" (e.g. {hints})" if hints else ""))
    lines.append("level:")
    lines.extend(f"- {lvl}: {desc}" for lvl, desc in LEVEL_GUIDE.items())
    return "\n".join(lines)


def enrichment_messages(item: EnrichmentInput, summary_language: str = "English") -> list[Message]:
    series = ", ".join(f"'{label}'" for label in SERIES_LABELS.values())
    system = f"""You catalogue internal 'minicode' knowledge-sharing recordings (Teams meeting recordings) for a searchable
company learning library. From the metadata and transcript, produce the catalogue entry.

Rules:
- title: '<Series>: <Topic>' where Series is one of {series} (normally 'Minicode'). Remove file-name artefacts
  (timestamps, 'Meeting Recording', '_' used instead of ':'), keep product names and customer names as written.
  Start from normalizedTitleSuggestion and only improve it if the transcript shows it is wrong or unclear.
- summary: 2-4 sentences in {summary_language}, what the viewer learns; concrete technologies; no speaker small talk.
- presenter: the person who gives the talk. Prefer the speaker with most talk time when it is a real name;
  otherwise the organizer. null if unknown. Never return labels like 'Speaker 1'.
- date: the recording date (YYYY-MM-DD) from recordedAt.
- topics: 1-3 topic tag ids from the taxonomy, most relevant first. Use 'general' only if nothing else fits.
- content_type and level: exactly one tag id each.
- language: language spoken in the recording (BCP-47).
- keywords: up to 8 specific search terms (technologies, products, concepts), in the transcript's language or English.
- Only use information in the input. Answer with the JSON object only.

Taxonomy:
{_taxonomy_text()}"""
    user = (
        f"<recording>\n{json.dumps(item.metadata(), ensure_ascii=False, indent=1)}\n</recording>\n"
        f"<transcript>\n{item.transcript_text()}\n</transcript>"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def retry_message(errors: list[str]) -> Message:
    bullets = "\n".join(f"- {e}" for e in errors)
    return {"role": "user", "content": f"The previous answer was invalid:\n{bullets}\nReturn a corrected JSON object."}


JUDGE_SCHEMA_NAME = "enrichment_judgement"
JUDGE_CRITERIA = ("accuracy", "tag_relevance", "summary_quality", "title_quality")


def judge_schema() -> dict[str, Any]:
    props: dict[str, Any] = {c: {"type": "integer", "enum": [1, 2, 3, 4, 5]} for c in JUDGE_CRITERIA}
    props["rationale"] = {"type": "string"}
    return {"type": "object", "additionalProperties": False, "required": [*JUDGE_CRITERIA, "rationale"], "properties": props}


def judge_messages(item: EnrichmentInput, output: dict[str, Any]) -> list[Message]:
    system = f"""You are a strict reviewer of catalogue entries for internal training recordings.
Score the candidate entry against the source on a 1-5 scale (5 = excellent, 3 = acceptable, 1 = wrong):
- accuracy: facts in title/summary/presenter/date are supported by the source; no hallucinations.
- tag_relevance: topics, content_type and level fit the content and the taxonomy below.
- summary_quality: concise, informative, tells a colleague what they will learn.
- title_quality: follows '<Series>: <Topic>', clean, specific.
Give a one-sentence rationale. Judge only what is in the source.

Taxonomy:
{_taxonomy_text()}"""
    user = (
        f"<source>\n{json.dumps(item.metadata(), ensure_ascii=False)}\n\n{item.transcript_text(8000)}\n</source>\n"
        f"<candidate>\n{json.dumps(output, ensure_ascii=False, indent=1)}\n</candidate>"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
