"""LLM adapter: Azure OpenAI, Claude on Microsoft Foundry, and a deterministic mock.

All implementations take chat messages plus a JSON schema and return the model's JSON text.
- AzureOpenAIChat: openai SDK `AzureOpenAI`, Entra ID auth (azure-identity bearer token provider),
  structured outputs (`response_format=json_schema`, strict).
- ClaudeFoundryChat: Anthropic Messages API on Foundry (`https://<resource>.services.ai.azure.com/anthropic`),
  Entra ID bearer token (scope https://ai.azure.com/.default) or API key; JSON is forced through a tool call.
- MockLLM: offline, deterministic; used by tests, local demo and the comparison harness dry run.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from minicode.enrichment.prompts import JUDGE_CRITERIA, JUDGE_SCHEMA_NAME, Message
from minicode.enrichment.schema import SCHEMA_NAME
from minicode.ingestion.http import RestClient, TokenProvider
from minicode.naming import normalize_title
from minicode.taxonomy import load_taxonomy

COGNITIVE_SCOPE = "https://cognitiveservices.azure.com/.default"
FOUNDRY_SCOPE = "https://ai.azure.com/.default"


@dataclass
class LLMResponse:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0


class LLMClient(Protocol):
    name: str

    def complete(self, messages: list[Message], schema: dict[str, Any], schema_name: str) -> LLMResponse: ...


class AzureOpenAIChat:
    def __init__(
        self,
        endpoint: str,
        deployment: str,
        api_version: str = "2024-10-21",
        credential: Any = None,
        api_key: str | None = None,
        http_client: httpx.Client | None = None,
        max_retries: int = 4,
    ) -> None:
        from openai import AzureOpenAI

        kwargs: dict[str, Any] = {"api_version": api_version, "azure_endpoint": endpoint, "max_retries": max_retries}
        if api_key:
            kwargs["api_key"] = api_key
        else:
            from azure.identity import DefaultAzureCredential, get_bearer_token_provider

            kwargs["azure_ad_token_provider"] = get_bearer_token_provider(credential or DefaultAzureCredential(), COGNITIVE_SCOPE)
        if http_client is not None:
            kwargs["http_client"] = http_client
        self._client = AzureOpenAI(**kwargs)
        self.deployment = deployment
        self.name = f"azure-openai:{deployment}"

    def complete(self, messages: list[Message], schema: dict[str, Any], schema_name: str) -> LLMResponse:
        resp = self._client.chat.completions.create(
            model=self.deployment,
            messages=messages,  # type: ignore[arg-type]
            temperature=0,
            response_format={"type": "json_schema", "json_schema": {"name": schema_name, "schema": schema, "strict": True}},
        )
        usage = resp.usage
        return LLMResponse(
            text=resp.choices[0].message.content or "",
            model=resp.model or self.deployment,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
        )


class ClaudeFoundryChat:
    """Claude via the Anthropic Messages API hosted in Microsoft Foundry."""

    def __init__(
        self,
        endpoint: str,
        deployment: str,
        tokens: TokenProvider | None = None,
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
        max_tokens: int = 2000,
    ) -> None:
        base = endpoint.rstrip("/")
        if not base.endswith("/anthropic"):
            base += "/anthropic"
        if tokens is None and not api_key:
            from minicode.ingestion.http import AzureIdentityTokenProvider

            tokens = AzureIdentityTokenProvider(FOUNDRY_SCOPE)
        self._api_key = api_key
        self._rest = RestClient(base, None if api_key else tokens, transport=transport, timeout=120.0)
        self.deployment = deployment
        self.max_tokens = max_tokens
        self.name = f"claude-foundry:{deployment}"

    def complete(self, messages: list[Message], schema: dict[str, Any], schema_name: str) -> LLMResponse:
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        chat = [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] != "system"]
        body = {
            "model": self.deployment,
            "max_tokens": self.max_tokens,
            "temperature": 0,
            "system": system,
            "messages": chat,
            "tools": [{"name": schema_name, "description": "Record the structured answer.", "input_schema": schema}],
            "tool_choice": {"type": "tool", "name": schema_name},
        }
        headers = {"anthropic-version": "2023-06-01", "content-type": "application/json"}
        if self._api_key:
            headers["x-api-key"] = self._api_key
        resp = self._rest.request("POST", "/v1/messages", auth=not self._api_key, json=body, headers=headers)
        data = resp.json()
        tool_input = next((b["input"] for b in data.get("content", []) if b.get("type") == "tool_use"), None)
        if tool_input is not None:
            text = json.dumps(tool_input, ensure_ascii=False)
        else:
            text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        usage = data.get("usage") or {}
        return LLMResponse(text, data.get("model", self.deployment), usage.get("input_tokens", 0), usage.get("output_tokens", 0))


_WORD = re.compile(r"[\wäöåÄÖÅ-]+")
_STOP = set(
    "the and for that this with you are have from was were what when will they them then than into our your about just "
    "also can not but all its it's there their which here how why one two use used using very more some like going "
    "okay hello hi everyone today talk minicode ja on se että ei ole tai kun niin mutta myös me se tämä kaikki".split()
)


def _block(prompt: str, tag: str) -> str:
    m = re.search(rf"<{tag}>\n?(.*?)\n?</{tag}>", prompt, re.S)
    return m.group(1) if m else ""


class MockLLM:
    """Deterministic stand-in for an LLM.

    profile "a": tags from the title only, presenter = organizer (behaves like a cautious small model).
    profile "b": tags from title + transcript keywords, presenter = top speaker (behaves like a stronger model).
    `invalid_first` makes the first N calls return invalid output to exercise the retry path.
    """

    def __init__(self, profile: str = "b", invalid_first: int = 0) -> None:
        if profile not in ("a", "b"):
            raise ValueError("profile must be 'a' or 'b'")
        self.profile = profile
        self.invalid_first = invalid_first
        self.calls = 0
        self.name = f"mock-{profile}"
        self._taxonomy = load_taxonomy()

    def complete(self, messages: list[Message], schema: dict[str, Any], schema_name: str) -> LLMResponse:
        self.calls += 1
        prompt = "\n".join(m["content"] for m in messages if m["role"] == "user")
        if self.calls <= self.invalid_first:
            out: dict[str, Any] = {"title": "", "topics": ["not-a-tag"], "level": 999}
        elif schema_name == SCHEMA_NAME:
            out = self._enrich(prompt)
        elif schema_name == JUDGE_SCHEMA_NAME:
            out = self._judge(prompt)
        else:
            raise ValueError(f"MockLLM does not know schema {schema_name!r}")
        text = json.dumps(out, ensure_ascii=False)
        return LLMResponse(text, self.name, input_tokens=len(prompt) // 4, output_tokens=len(text) // 4)

    def _enrich(self, prompt: str) -> dict[str, Any]:
        meta = json.loads(_block(prompt, "recording") or "{}")
        transcript = _block(prompt, "transcript")
        raw_title = meta.get("rawTitle", "")
        norm = normalize_title(raw_title)
        title = meta.get("normalizedTitleSuggestion") or norm.display
        t = self._taxonomy
        title_text = f"{raw_title} {norm.title}".lower()
        body = re.sub(r"\[\d+:\d+(:\d+)?\]", " ", transcript).lower()
        scores: Counter[str] = Counter()
        for tag in t.topic.tags:
            if tag.id == t.topic.fallback:
                continue
            if tag.matches(title_text):
                scores[tag.id] += 10
            if self.profile == "b" and body:
                scores[tag.id] += sum(len(p.findall(body)) for p in tag.patterns)
        min_score = 10 if self.profile == "a" else 3
        topics = [tid for tid, s in scores.most_common() if s >= min_score][:3] or [t.topic.fallback or "general"]
        ct_text = title_text + (" " + body[:3000] if self.profile == "b" else "")
        content_type = next((tag.id for tag in t.content_type.tags if tag.matches(ct_text)), t.content_type.default)
        level = int(norm.level_hint or t.level.default or 200)
        if self.profile == "b" and norm.level_hint is None and len(re.findall(r"internals|architecture|deep dive", body)) >= 2:
            level = 300

        talk = meta.get("speakerTalkTimeSeconds") or {}
        presenter = meta.get("organizer")
        if self.profile == "b" and talk:
            top = max(talk.items(), key=lambda kv: kv[1])[0]
            presenter = presenter if re.fullmatch(r"(?i)speaker\s*\d+", top) else top
        if norm.presenter:
            presenter = norm.presenter

        words = [w.lower() for w in _WORD.findall(body) if len(w) > 3 and w.lower() not in _STOP]
        keywords = [w for w, _ in Counter(words).most_common(8)] if self.profile == "b" else []
        spoken = re.sub(r"(?m)^\s*(\[\d[\d:]*\]\s*)?[^:\n]{2,40}: ", "", transcript)
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", spoken)) if s.strip()]
        lead = " ".join(sentences[: 1 if self.profile == "a" else 3])[:500]
        focus = ", ".join(t.topic.get(tid).label for tid in topics if t.topic.get(tid)) if topics else "general"
        summary = f"{title.split(': ', 1)[-1]} - a {t.content_type.get(content_type).label.lower()} on {focus}."
        if lead:
            summary += f" {lead}"
        summary = summary if len(summary) >= 60 else summary + " Recorded as an internal minicode session."
        language = meta.get("transcriptLanguage") or ("fi-FI" if re.search(r"[äö]", raw_title) else "en-US")
        recorded = meta.get("recordedAt")
        return {
            "title": title,
            "summary": summary,
            "presenter": presenter,
            "date": recorded[:10] if recorded else None,
            "topics": topics,
            "content_type": content_type,
            "level": level,
            "language": language,
            "keywords": keywords,
            "confidence": 0.55 if self.profile == "a" else 0.8,
        }

    def _judge(self, prompt: str) -> dict[str, Any]:
        cand = json.loads(_block(prompt, "candidate") or "{}")
        source = _block(prompt, "source").lower()
        has_transcript = "\n" in source.strip() and len(source) > 600
        scores = {c: 3 for c in JUDGE_CRITERIA}
        if cand.get("presenter") and str(cand["presenter"]).lower() in source:
            scores["accuracy"] += 1
        if has_transcript and cand.get("keywords"):
            scores["accuracy"] += 1
        n_topics = len(cand.get("topics") or [])
        scores["tag_relevance"] += 1 if 1 <= n_topics <= 3 and "general" not in (cand.get("topics") or []) else -1
        if has_transcript and n_topics >= 2:
            scores["tag_relevance"] += 1
        summary = cand.get("summary") or ""
        scores["summary_quality"] += 1 if len(summary) > 160 else 0
        scores["summary_quality"] -= 1 if len(summary) < 90 else 0
        title = cand.get("title") or ""
        scores["title_quality"] += 1 if re.match(r"^[\w &]+: \S", title) else -1
        scores = {k: min(5, max(1, v)) for k, v in scores.items()}
        return {**scores, "rationale": "Deterministic mock judgement (heuristic, not a real model)."}
