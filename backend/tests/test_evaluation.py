from __future__ import annotations

import csv
import json
from dataclasses import replace

import pytest

from minicode.enrichment.llm import MockLLM
from minicode.evaluation.__main__ import main, parse_prices
from minicode.evaluation.harness import ModelSummary, composite, load_evalset, pick_model, validate_gold
from minicode.evaluation.report import REVIEW_COLUMNS
from minicode.taxonomy import load_taxonomy


@pytest.fixture(scope="module")
def items():  # noqa: ANN201
    return load_evalset()


def test_evalset_has_20_items_with_valid_gold(items) -> None:  # noqa: ANN001
    assert 15 <= len(items) <= 20 and len({i.id for i in items}) == len(items)
    assert validate_gold(items, load_taxonomy()) == []
    with_transcript = [i for i in items if i.has_transcript]
    assert 5 <= len(with_transcript) < len(items)
    assert all(i.input.chunks for i in with_transcript) and all(not i.input.chunks for i in items if not i.has_transcript)


def test_validate_gold_flags_unknown_tags(items) -> None:  # noqa: ANN001
    broken = replace(items[0], gold=replace(items[0].gold, topics=["not-a-topic"]))
    assert validate_gold([broken], load_taxonomy())


def test_composite_renormalizes_missing_checks() -> None:
    perfect = {"topic_f1": 1.0, "content_type": 1.0, "level": 1.0, "presenter": None, "first_try_valid": 1.0}
    assert composite(perfect, 1.0) == 1.0
    assert composite(perfect, None) == 1.0
    assert composite({**perfect, "topic_f1": 0.0}, 1.0) == pytest.approx(1 - 0.25 / 0.9, abs=1e-4)


def _summary(client: str, score: float, latency: float = 1.0, cost: float | None = None) -> ModelSummary:
    return ModelSummary(client, client, 20, 0, score, None, {}, {}, score, score, 0, latency, 0, 0, cost)


def test_pick_model_rules() -> None:
    assert pick_model([_summary("a", 0.80), _summary("b", 0.85)])[0] == "b"
    pick, reason = pick_model([_summary("a", 0.84, cost=2.0), _summary("b", 0.85, cost=5.0)])
    assert pick == "a" and "cheaper" in reason
    pick, reason = pick_model([_summary("a", 0.84, latency=1.0), _summary("b", 0.85, latency=3.0)])
    assert pick == "a" and "faster" in reason
    pick, reason = pick_model([_summary("a", 0.84, latency=1.0), _summary("b", 0.85, latency=1.02)])
    assert pick == "b" and "provisional" in reason
    assert pick_model([]) == (None, "no models evaluated")


def test_parse_prices() -> None:
    assert parse_prices(["azure-openai:gpt-4.1-mini=0.4/1.6"]) == {"azure-openai:gpt-4.1-mini": (0.4, 1.6)}
    with pytest.raises((SystemExit, ValueError)):
        parse_prices(["broken"])


def test_cli_end_to_end_on_mocks(tmp_path) -> None:  # noqa: ANN001
    report, out = tmp_path / "report.md", tmp_path / "eval"
    assert main(["--limit", "6", "--report", str(report), "--out", str(out), "-q"]) == 0
    text = report.read_text(encoding="utf-8")
    assert "mock" in text.lower() and "mock-a" in text and "mock-b" in text and "## Result" in text and "## Human tag spot check" in text
    results = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert {s["client"] for s in results["summaries"]} == {"mock-a", "mock-b"} and results["mock"] is True
    assert len(results["results"]) == 12 and results["pick"] in {"mock-a", "mock-b"}
    with (out / "tag-review.csv").open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows and list(rows[0]) == REVIEW_COLUMNS and len(rows) == 12
    assert all(r["reviewer_topics_ok"] == "" for r in rows)


def test_mock_model_is_deterministic(items) -> None:  # noqa: ANN001
    from minicode.enrichment.enricher import Enricher

    taxonomy = load_taxonomy()
    a1 = Enricher(MockLLM("a"), taxonomy).enrich(items[0].input).enrichment.to_dict()
    a2 = Enricher(MockLLM("a"), taxonomy).enrich(items[0].input).enrichment.to_dict()
    assert a1 == a2
