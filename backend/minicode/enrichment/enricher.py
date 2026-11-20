"""Run the LLM with schema validation, taxonomy constraints and retry-with-feedback."""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field

from minicode.enrichment.inputs import EnrichmentInput
from minicode.enrichment.llm import LLMClient
from minicode.enrichment.prompts import enrichment_messages, retry_message
from minicode.enrichment.schema import SCHEMA_NAME, Enrichment, json_schema, validate
from minicode.taxonomy import Taxonomy, load_taxonomy

log = logging.getLogger(__name__)


class EnrichmentError(RuntimeError):
    pass


@dataclass
class EnrichmentOutcome:
    enrichment: Enrichment
    model: str
    attempts: int
    needs_review: bool
    errors: list[str] = field(default_factory=list)  # validation errors seen along the way
    input_tokens: int = 0
    output_tokens: int = 0
    latency_seconds: float = 0.0


def parse_json(text: str) -> object:
    """Parse model output, tolerating ```json fences or prose around the object."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if 0 <= start < end:
            return json.loads(text[start : end + 1])
        raise


class Enricher:
    def __init__(
        self,
        llm: LLMClient,
        taxonomy: Taxonomy | None = None,
        max_attempts: int = 3,
        summary_language: str = "English",
        review_confidence: float = 0.5,
    ) -> None:
        self.llm = llm
        self.taxonomy = taxonomy or load_taxonomy()
        self.max_attempts = max_attempts
        self.summary_language = summary_language
        self.review_confidence = review_confidence
        self.schema = json_schema(self.taxonomy)

    def enrich(self, item: EnrichmentInput) -> EnrichmentOutcome:
        messages = enrichment_messages(item, self.summary_language)
        seen: list[str] = []
        tokens_in = tokens_out = 0
        started = time.perf_counter()
        last_partial = None
        for attempt in range(1, self.max_attempts + 1):
            resp = self.llm.complete(messages, self.schema, SCHEMA_NAME)
            tokens_in += resp.input_tokens
            tokens_out += resp.output_tokens
            try:
                result = validate(parse_json(resp.text), self.taxonomy)
            except (json.JSONDecodeError, ValueError) as exc:
                errors = [f"output is not valid JSON: {exc}"]
                result = None
            else:
                errors = result.errors
                if result.ok and result.enrichment:
                    e = result.enrichment
                    needs_review = e.confidence < self.review_confidence
                    return EnrichmentOutcome(e, resp.model, attempt, needs_review, seen, tokens_in, tokens_out,
                                             time.perf_counter() - started)
                if result.tag_errors_only:
                    last_partial = (result.enrichment, resp.model)
            seen.extend(errors)
            log.info("enrichment of %s attempt %d invalid: %s", item.recording_id, attempt, "; ".join(errors))
            messages = [*messages, {"role": "assistant", "content": resp.text}, retry_message(errors)]
        if last_partial and last_partial[0] is not None:
            # Usable apart from tags: keep the valid tags, flag for admin review.
            return EnrichmentOutcome(last_partial[0], last_partial[1], self.max_attempts, True, seen, tokens_in, tokens_out,
                                     time.perf_counter() - started)
        raise EnrichmentError(f"{item.recording_id}: no valid output after {self.max_attempts} attempts: {'; '.join(seen[-3:])}")
