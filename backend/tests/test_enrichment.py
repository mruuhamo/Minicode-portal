from __future__ import annotations

import json
from typing import Any

import pytest

from minicode.enrichment.enricher import Enricher, EnrichmentError, parse_json
from minicode.enrichment.inputs import EnrichmentInput, mmss
from minicode.enrichment.llm import LLMResponse, MockLLM
from minicode.enrichment.repository import (
    InMemoryRepository,
    LocalJsonRepository,
    PatchError,
    apply_llm,
    apply_patch,
    compute_effective,
    new_document,
    validate_patch,
)
from minicode.enrichment.schema import json_schema, validate
from minicode.taxonomy import load_taxonomy

SUMMARY = "A walkthrough of publishing Bicep modules to a private Azure Container Registry and consuming them from pipelines."


def good(**overrides: Any) -> dict[str, Any]:
    data = {
        "title": "Minicode: Bicep private registry", "summary": SUMMARY, "presenter": "Aino Virtanen", "date": "2026-11-02",
        "topics": ["devops-iac", "azure-platform"], "content_type": "knowledge-share", "level": 200, "language": "en-US",
        "keywords": ["bicep", "acr"], "confidence": 0.9,
    }
    return {**data, **overrides}


class ScriptedLLM:
    name = "scripted"

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.seen: list[list[dict[str, str]]] = []

    def complete(self, messages, schema, schema_name):  # noqa: ANN001, ANN201
        self.seen.append(list(messages))
        return LLMResponse(self.replies.pop(0), "scripted-model", 100, 50)


ITEM = EnrichmentInput("rec1", "Minicode_ Bicep private registry-20261102_100114-Meeting Recording", organizer="Aino Virtanen",
                       recorded_at="2026-11-02T10:01:14Z")


def test_validate_accepts_good_output_and_normalizes() -> None:
    r = validate(good(topics=["DevOps-IaC", "general"], presenter="Speaker 1", date="2026-11-02T10:00:00Z"))
    assert r.ok and r.errors == []
    assert r.enrichment.topics == ["devops-iac"]  # case-folded, 'general' dropped next to a real topic
    assert r.enrichment.presenter is None  # diarization label is not a name
    assert r.enrichment.date == "2026-11-02"


@pytest.mark.parametrize(
    ("data", "fragment"),
    [
        (good(title="Minicode_ Bicep-20261102_100114-Meeting Recording"), "artefacts"),
        (good(summary="too short"), "summary"),
        (good(language="english"), "language"),
        (good(date="02.11.2026"), "date"),
        ({"title": "x"}, "missing properties"),
        ([], "JSON object"),
    ],
)
def test_validate_rejects_structural_errors(data: Any, fragment: str) -> None:
    r = validate(data)
    assert r.enrichment is None and not r.tag_errors_only
    assert any(fragment in e for e in r.errors)


def test_validate_drops_unknown_tags_but_reports_them() -> None:
    r = validate(good(topics=["devops-iac", "kubernetes"], level=250, content_type="webinar"))
    assert r.enrichment is not None and r.tag_errors_only
    assert r.enrichment.topics == ["devops-iac"] and r.enrichment.level in (100, 200, 300, 400)
    assert len(r.errors) == 3


def test_json_schema_is_strict_and_constrains_tags() -> None:
    schema = json_schema()
    assert schema["additionalProperties"] is False and set(schema["required"]) == set(schema["properties"])
    assert set(schema["properties"]["topics"]["items"]["enum"]) == set(load_taxonomy().topic.tag_ids())


def test_parse_json_tolerates_fences_and_prose() -> None:
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Sure! {"a": {"b": 2}} hope this helps') == {"a": {"b": 2}}
    with pytest.raises(json.JSONDecodeError):
        parse_json("no json here")


def test_enricher_retries_with_error_feedback() -> None:
    llm = ScriptedLLM("not json", json.dumps(good(summary="short")), json.dumps(good()))
    out = Enricher(llm, load_taxonomy()).enrich(ITEM)
    assert out.attempts == 3 and not out.needs_review
    assert out.enrichment.title == "Minicode: Bicep private registry"
    assert out.input_tokens == 300 and out.output_tokens == 150
    retry_prompt = llm.seen[2][-1]["content"]
    assert llm.seen[2][-2]["role"] == "assistant" and "summary" in retry_prompt


def test_enricher_falls_back_to_tag_errors_only_result_with_review_flag() -> None:
    bad_tags = json.dumps(good(topics=["devops-iac", "made-up"]))
    out = Enricher(ScriptedLLM(bad_tags, bad_tags), load_taxonomy(), max_attempts=2).enrich(ITEM)
    assert out.needs_review and out.enrichment.topics == ["devops-iac"]


def test_enricher_raises_when_nothing_usable() -> None:
    with pytest.raises(EnrichmentError):
        Enricher(ScriptedLLM("{}", "{}"), load_taxonomy(), max_attempts=2).enrich(ITEM)


def test_low_confidence_needs_review() -> None:
    out = Enricher(ScriptedLLM(json.dumps(good(confidence=0.2))), load_taxonomy()).enrich(ITEM)
    assert out.needs_review


@pytest.mark.parametrize("profile", ["a", "b"])
def test_mock_llm_is_deterministic_and_valid(profile: str) -> None:
    a = Enricher(MockLLM(profile), load_taxonomy()).enrich(ITEM)
    b = Enricher(MockLLM(profile), load_taxonomy()).enrich(ITEM)
    assert a.enrichment == b.enrichment and a.attempts == 1
    assert "devops-iac" in a.enrichment.topics and a.enrichment.date == "2026-11-02"


def test_mock_llm_invalid_first_exercises_retry() -> None:
    out = Enricher(MockLLM("b", invalid_first=1), load_taxonomy()).enrich(ITEM)
    assert out.attempts == 2


def test_input_transcript_sampling_and_hash() -> None:
    chunks = [{"start": i * 60.0, "end": i * 60.0 + 60, "text": f"Aino: part {i} " + "x" * 200, "speakers": ["Aino"]}
              for i in range(50)]
    item = EnrichmentInput("r", "Minicode_ X", chunks=chunks)
    text = item.transcript_text(max_chars=2000)
    assert len(text) <= 2000 and "[00:00]" in text and "[...]" in text
    assert item.speaker_seconds() == [("Aino", 3000)]
    assert item.input_hash("v1", "m") != item.input_hash("v2", "m")
    assert mmss(3725) == "1:02:05" and mmss(65) == "01:05"


# --- repository: overrides win -----------------------------------------------------------------------


def _doc() -> dict[str, Any]:
    doc = new_document("rec1", {"rawTitle": "Minicode_ Bicep private registry-20261102_100114-Meeting Recording",
                                "recordedAt": "2026-11-02T10:01:14Z", "organizer": "Aino Virtanen"})
    return compute_effective(doc)


def test_fallback_values_before_enrichment() -> None:
    doc = _doc()
    assert doc["title"] == "Minicode: Bicep private registry" and "devops-iac" in doc["topics"]
    assert doc["date"] == "2026-11-02" and doc["presenter"] == "Aino Virtanen" and doc["summary"] is None


def test_admin_overrides_survive_re_enrichment_and_null_reverts() -> None:
    doc = apply_llm(_doc(), good(title="LLM title: one"), {"model": "m1"})
    assert doc["title"] == "LLM title: one"
    audit = apply_patch(doc, validate_patch({"title": "Admin title", "topics": ["azure-platform"]}), user="admin@x")
    assert audit["changes"]["title"] == {"from": "LLM title: one", "to": "Admin title"}
    doc = apply_llm(doc, good(title="LLM title: two"), {"model": "m2"})  # re-enrichment
    assert doc["title"] == "Admin title" and doc["topics"] == ["azure-platform"]
    assert doc["llm"]["title"] == "LLM title: two" and doc["overriddenFields"] == ["title", "topics"]
    apply_patch(doc, validate_patch({"title": None}), user="admin@x")
    assert doc["title"] == "LLM title: two" and doc["overriddenFields"] == ["topics"]


def test_hidden_override() -> None:
    doc = _doc()
    apply_patch(doc, validate_patch({"hidden": True}), user="a")
    assert doc["hidden"] is True


@pytest.mark.parametrize(
    "patch",
    [{}, {"rawTitle": "x"}, {"topics": ["nope"]}, {"topics": []}, {"level": 250}, {"contentType": "webinar"},
     {"date": "yesterday"}, {"title": "  "}, {"hidden": "yes"}, {"keywords": "a,b"}],
)
def test_validate_patch_rejects(patch: dict[str, Any]) -> None:
    with pytest.raises(PatchError):
        validate_patch(patch)


def test_validate_patch_coerces() -> None:
    assert validate_patch({"level": "300", "title": " T ", "topics": ["ai-genai", "ai-genai"]}) == {
        "level": 300, "title": "T", "topics": ["ai-genai"]}


@pytest.mark.parametrize("kind", ["memory", "local"])
def test_repositories_round_trip(kind: str, tmp_path) -> None:  # noqa: ANN001
    repo = InMemoryRepository() if kind == "memory" else LocalJsonRepository(tmp_path)
    doc = _doc()
    repo.upsert(doc)
    repo.add_audit({"id": "a1", "recordingId": "rec1", "at": "2026-11-02T00:00:00+00:00", "user": "u", "changes": {}})
    assert repo.get("rec1")["title"] == doc["title"] and [d["id"] for d in repo.list()] == ["rec1"]
    assert [a["id"] for a in repo.audit("rec1")] == ["a1"] and repo.audit("other") == []
    repo.delete("rec1")
    assert repo.get("rec1") is None


# --- pipeline -----------------------------------------------------------------------------------------


def test_pipeline_enriches_all_and_is_idempotent(demo) -> None:  # noqa: ANN001
    first = demo.enrichment_pipeline.run()
    assert first.counts["enriched"] == 7 and not first.errors and len(first.changed) == 7
    docs = list(demo.repository.list())
    assert all(d["enrichment"]["inputHash"] and d["summary"] for d in docs)
    assert {d["transcriptSource"] for d in docs} == {"teams-vtt", "azure-speech"}
    second = demo.enrichment_pipeline.run()
    assert second.counts.get("enriched", 0) == 0 and second.changed == []
    assert demo.enrichment_pipeline.run(force=True, only=[docs[0]["id"]]).changed == [docs[0]["id"]]


def test_pipeline_records_failures_with_fallback(demo, monkeypatch) -> None:  # noqa: ANN001
    demo.enricher.llm = ScriptedLLM(*["{}"] * 30)
    summary = demo.enrichment_pipeline.run()
    assert len(summary.errors) == 7
    doc = next(iter(demo.repository.list()))
    assert doc["enrichmentError"] and doc["title"].startswith("Minicode:")  # week 1 fallback still searchable
