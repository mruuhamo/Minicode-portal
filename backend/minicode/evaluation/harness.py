"""Model comparison harness (week 3): run candidate LLMs over the eval set and score them.

Scoring per item = deterministic checks against the gold labels + LLM-as-judge rubric (1-5 per criterion).
Outputs: results JSON, a CSV for the human tag spot check and a markdown report (see report.py).
"""

from __future__ import annotations

import hashlib
import json
import re
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from minicode.enrichment.enricher import Enricher, EnrichmentError, EnrichmentOutcome, parse_json
from minicode.enrichment.inputs import EnrichmentInput
from minicode.enrichment.llm import LLMClient
from minicode.enrichment.prompts import JUDGE_CRITERIA, JUDGE_SCHEMA_NAME, judge_messages, judge_schema
from minicode.ingestion.chunking import chunk_transcript
from minicode.ingestion.fakes import SAMPLES_DIR, speech_result_from_script
from minicode.ingestion.transcripts import parse_speech_result, parse_vtt
from minicode.taxonomy import Taxonomy, load_taxonomy

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_EVALSET = REPO_ROOT / "data" / "eval" / "evalset.yaml"
WEIGHTS = {"judge": 0.35, "topic_f1": 0.25, "content_type": 0.10, "level": 0.10, "presenter": 0.10, "first_try_valid": 0.10}
TIE_MARGIN = 0.03
TITLE_ARTEFACTS = re.compile(r"meeting recording|\d{8}_\d{6}|\\_|\.mp4$", re.I)
TITLE_SHAPE = re.compile(r"^[^:]{2,40}: \S")


@dataclass
class Gold:
    primary: list[str]
    topics: list[str]
    content_type: list[str]
    level: int | None = None
    presenter: str | None = None


@dataclass
class EvalItem:
    id: str
    input: EnrichmentInput
    gold: Gold

    @property
    def has_transcript(self) -> bool:
        return bool(self.input.chunks)


def _sample_input(item_id: str, sample: str, reference: date, samples_dir: Path) -> EnrichmentInput:
    spec = json.loads((samples_dir / "recordings.json").read_text(encoding="utf-8"))
    entry = next((e for e in spec["items"] if sample in (e.get("transcript"), e.get("speech"))), None)
    if entry is None:
        raise ValueError(f"eval item {item_id}: sample {sample!r} not in recordings.json")
    recorded = datetime.combine(reference - timedelta(days=entry["days_ago"]), datetime.min.time()).replace(hour=10)
    text = (samples_dir / ("transcripts" if entry.get("transcript") else "speech") / sample).read_text(encoding="utf-8")
    if entry.get("transcript"):
        transcript = parse_vtt(text, recording_id=item_id)
    else:
        transcript = parse_speech_result(speech_result_from_script(text, sample), recording_id=item_id)
    return EnrichmentInput(
        recording_id=item_id,
        raw_title=f"{entry['stem']}-{recorded:%Y%m%d}_100114-Meeting Recording",
        organizer=entry.get("organizer"),
        recorded_at=recorded.isoformat() + "Z",
        duration_seconds=int(entry.get("duration_min", 1) * 60),
        language=getattr(transcript, "language", None),
        transcript_source=transcript.source,
        chunks=[c.to_dict() for c in chunk_transcript(transcript)],
    )


def load_evalset(path: Path = DEFAULT_EVALSET, samples_dir: Path = SAMPLES_DIR) -> list[EvalItem]:
    spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    reference = date.fromisoformat(str(spec["reference_date"]))
    items: list[EvalItem] = []
    for raw in spec["items"]:
        g = raw["gold"]
        gold = Gold(list(g["primary"]), list(g["topics"]), list(g["content_type"]), g.get("level"), g.get("presenter"))
        if not set(gold.primary) <= set(gold.topics):
            raise ValueError(f"eval item {raw['id']}: primary tags must be listed in topics")
        if raw.get("sample"):
            inp = _sample_input(raw["id"], raw["sample"], reference, samples_dir)
        else:
            inp = EnrichmentInput(recording_id=raw["id"], raw_title=raw["title"], organizer=raw.get("organizer"))
        items.append(EvalItem(raw["id"], inp, gold))
    if len({i.id for i in items}) != len(items):
        raise ValueError("duplicate eval item ids")
    return items


def validate_gold(items: Sequence[EvalItem], taxonomy: Taxonomy) -> list[str]:
    topics, types = set(taxonomy.topic.tag_ids()), set(taxonomy.content_type.tag_ids())
    problems = []
    for it in items:
        problems += [f"{it.id}: unknown topic {t}" for t in it.gold.topics if t not in topics]
        problems += [f"{it.id}: unknown content type {t}" for t in it.gold.content_type if t not in types]
    return problems


# --- deterministic checks ---------------------------------------------------------------------------


def _norm(name: str | None) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().casefold())


def deterministic_checks(item: EvalItem, outcome: EnrichmentOutcome) -> dict[str, Any]:
    e, g = outcome.enrichment, item.gold
    predicted = list(e.topics)
    correct = [t for t in predicted if t in g.topics]
    precision = len(correct) / len(predicted) if predicted else 0.0
    recall = len([t for t in g.primary if t in predicted]) / len(g.primary)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    presenter: float | None = None
    if g.presenter:
        pred, gold = _norm(e.presenter), _norm(g.presenter)
        presenter = 1.0 if pred == gold or (pred and gold in pred.split(" ")) else 0.0
    expected_date = item.input.recorded_at[:10] if item.input.recorded_at else None
    return {
        "topic_precision": round(precision, 3),
        "topic_recall": round(recall, 3),
        "topic_f1": round(f1, 3),
        "content_type": 1.0 if e.content_type in g.content_type else 0.0,
        "level": None if g.level is None or e.level is None else (1.0 if abs(int(e.level) - g.level) <= 100 else 0.0),
        "presenter": presenter,
        "date_ok": e.date == expected_date,  # no transcript/date -> must not invent one
        "title_clean": bool(TITLE_SHAPE.match(e.title)) and not TITLE_ARTEFACTS.search(e.title),
        "first_try_valid": 1.0 if outcome.attempts == 1 and not outcome.needs_review else 0.0,
        "attempts": outcome.attempts,
    }


# --- judge ------------------------------------------------------------------------------------------


def judge(judges: Sequence[LLMClient], item: EvalItem, output: dict[str, Any]) -> dict[str, Any]:
    """Average rubric scores over one or more judges (use >1 judge to dampen self-preference bias)."""
    per_judge: list[dict[str, Any]] = []
    for j in judges:
        try:
            resp = j.complete(judge_messages(item.input, output), judge_schema(), JUDGE_SCHEMA_NAME)
            data = parse_json(resp.text)
            if not isinstance(data, dict):
                raise ValueError("judge output is not an object")
            scores = {c: int(data[c]) for c in JUDGE_CRITERIA}
            if not all(1 <= s <= 5 for s in scores.values()):
                raise ValueError("judge score out of range")
            per_judge.append({"judge": j.name, **scores, "rationale": str(data.get("rationale", ""))[:400]})
        except Exception as e:  # noqa: BLE001 - a broken judge reply must not sink the run
            per_judge.append({"judge": j.name, "error": str(e)[:200]})
    ok = [p for p in per_judge if "error" not in p]
    if not ok:
        return {"scores": None, "normalized": None, "judges": per_judge}
    scores = {c: round(statistics.mean(p[c] for p in ok), 2) for c in JUDGE_CRITERIA}
    normalized = statistics.mean((s - 1) / 4 for s in scores.values())
    return {"scores": scores, "normalized": round(normalized, 3), "judges": per_judge}


def composite(checks: dict[str, Any], judge_normalized: float | None) -> float:
    values = {**{k: checks.get(k) for k in WEIGHTS if k != "judge"}, "judge": judge_normalized}
    applicable = {k: w for k, w in WEIGHTS.items() if values[k] is not None}
    return round(sum(w * float(values[k]) for k, w in applicable.items()) / sum(applicable.values()), 4)


# --- run --------------------------------------------------------------------------------------------


@dataclass
class ItemResult:
    item_id: str
    model: str
    ok: bool
    output: dict[str, Any] | None = None
    checks: dict[str, Any] = field(default_factory=dict)
    judge: dict[str, Any] = field(default_factory=dict)
    composite: float = 0.0
    attempts: int = 0
    needs_review: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    latency_seconds: float = 0.0
    error: str | None = None


@dataclass
class ModelSummary:
    model: str
    client: str
    items: int
    failures: int
    composite: float
    judge: float | None
    judge_scores: dict[str, float]
    metrics: dict[str, float | None]
    with_transcript: float
    title_only: float
    needs_review: int
    mean_latency: float
    input_tokens: int
    output_tokens: int
    cost: float | None = None


@dataclass
class Comparison:
    evalset: str
    evalset_hash: str
    judges: list[str]
    summaries: list[ModelSummary]
    results: list[ItemResult]
    pick: str | None
    pick_reason: str
    mock: bool

    def to_dict(self) -> dict[str, Any]:
        from dataclasses import asdict

        return asdict(self)


def run_model(llm: LLMClient, items: Sequence[EvalItem], judges: Sequence[LLMClient], taxonomy: Taxonomy,
              summary_language: str = "English", progress: Callable[[str], None] | None = None) -> list[ItemResult]:
    enricher = Enricher(llm, taxonomy, summary_language=summary_language)
    results: list[ItemResult] = []
    for item in items:
        if progress:
            progress(f"{llm.name}: {item.id}")
        try:
            outcome = enricher.enrich(item.input)
        except EnrichmentError as e:
            results.append(ItemResult(item.id, llm.name, ok=False, error=str(e)[:300], attempts=enricher.max_attempts))
            continue
        output = outcome.enrichment.to_dict()
        checks = deterministic_checks(item, outcome)
        verdict = judge(judges, item, output)
        results.append(ItemResult(
            item.id, outcome.model or llm.name, ok=True, output=output, checks=checks, judge=verdict,
            composite=composite(checks, verdict["normalized"]), attempts=outcome.attempts, needs_review=outcome.needs_review,
            input_tokens=outcome.input_tokens, output_tokens=outcome.output_tokens,
            latency_seconds=round(outcome.latency_seconds, 2),
        ))
    return results


def _mean(values: list[float | None]) -> float | None:
    vals = [float(v) for v in values if v is not None]
    return round(statistics.mean(vals), 3) if vals else None


def summarize(client: str, results: list[ItemResult], items: Sequence[EvalItem],
              price: tuple[float, float] | None = None) -> ModelSummary:
    by_id = {i.id: i for i in items}
    ok = [r for r in results if r.ok]
    judged = [r for r in ok if r.judge.get("scores")]
    metric_names = ("topic_precision", "topic_recall", "topic_f1", "content_type", "level", "presenter", "first_try_valid")
    metrics: dict[str, float | None] = {m: _mean([r.checks.get(m) for r in ok]) for m in metric_names}
    metrics["date_ok"] = _mean([1.0 if r.checks.get("date_ok") else 0.0 for r in ok])
    metrics["title_clean"] = _mean([1.0 if r.checks.get("title_clean") else 0.0 for r in ok])
    tin, tout = sum(r.input_tokens for r in results), sum(r.output_tokens for r in results)
    return ModelSummary(
        model=ok[0].model if ok else client,
        client=client,
        items=len(results),
        failures=len(results) - len(ok),
        composite=round(statistics.mean(r.composite for r in results), 4) if results else 0.0,  # failures count as 0
        judge=_mean([r.judge["normalized"] for r in judged]),
        judge_scores={c: _mean([r.judge["scores"][c] for r in judged]) or 0.0 for c in JUDGE_CRITERIA},
        metrics=metrics,
        with_transcript=_mean([r.composite for r in results if by_id[r.item_id].has_transcript]) or 0.0,
        title_only=_mean([r.composite for r in results if not by_id[r.item_id].has_transcript]) or 0.0,
        needs_review=sum(1 for r in ok if r.needs_review),
        mean_latency=round(statistics.mean(r.latency_seconds for r in ok), 2) if ok else 0.0,
        input_tokens=tin,
        output_tokens=tout,
        cost=round((tin * price[0] + tout * price[1]) / 1_000_000, 4) if price else None,
    )


def pick_model(summaries: Sequence[ModelSummary]) -> tuple[str | None, str]:
    ranked = sorted(summaries, key=lambda s: s.composite, reverse=True)
    if not ranked:
        return None, "no models evaluated"
    if len(ranked) == 1:
        return ranked[0].client, "only one model evaluated"
    best, runner = ranked[0], ranked[1]
    gap = best.composite - runner.composite
    if gap >= TIE_MARGIN:
        return best.client, f"highest composite score ({best.composite:.3f} vs {runner.composite:.3f}, margin {gap:.3f})"
    if best.cost is not None and runner.cost is not None and best.cost != runner.cost:
        cheaper = min((best, runner), key=lambda s: s.cost or 0.0)
        return cheaper.client, f"composite scores within {TIE_MARGIN} ({gap:.3f}); picked the cheaper model"
    faster, slower = sorted((best, runner), key=lambda s: s.mean_latency)
    if slower.mean_latency - faster.mean_latency > max(0.05, 0.1 * slower.mean_latency):
        return faster.client, f"composite scores within {TIE_MARGIN} ({gap:.3f}); picked the faster model (no prices given)"
    return best.client, (f"composite scores within {TIE_MARGIN} ({gap:.3f}) and no clear cost/latency difference; "
                         "provisional pick on composite - decide on cost, data residency and the human tag review")


def compare(models: Sequence[LLMClient], judges: Sequence[LLMClient], items: Sequence[EvalItem],
            evalset_path: Path = DEFAULT_EVALSET, taxonomy: Taxonomy | None = None,
            prices: dict[str, tuple[float, float]] | None = None, summary_language: str = "English",
            progress: Callable[[str], None] | None = None) -> Comparison:
    taxonomy = taxonomy or load_taxonomy()
    if problems := validate_gold(items, taxonomy):
        raise ValueError("eval set gold labels do not match the taxonomy: " + "; ".join(problems))
    results: list[ItemResult] = []
    summaries: list[ModelSummary] = []
    for llm in models:
        model_results = run_model(llm, items, judges, taxonomy, summary_language, progress)
        results += model_results
        summaries.append(summarize(llm.name, model_results, items, (prices or {}).get(llm.name)))
    pick, reason = pick_model(summaries)
    names = [m.name for m in models] + [j.name for j in judges]
    return Comparison(
        evalset=evalset_path.name if evalset_path.is_absolute() else str(evalset_path),
        evalset_hash=hashlib.sha256(evalset_path.read_bytes()).hexdigest()[:12] if evalset_path.exists() else "",
        judges=[j.name for j in judges], summaries=summaries, results=results, pick=pick, pick_reason=reason,
        mock=any(n.startswith("mock") for n in names),
    )
