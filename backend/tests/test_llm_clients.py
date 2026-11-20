from __future__ import annotations

import json

import httpx
import pytest

from minicode.enrichment.embeddings import AzureOpenAIEmbedder, HashEmbedder, tokenize
from minicode.enrichment.inputs import EnrichmentInput
from minicode.enrichment.llm import AzureOpenAIChat, ClaudeFoundryChat
from minicode.enrichment.prompts import enrichment_messages
from minicode.enrichment.schema import SCHEMA_NAME, json_schema
from minicode.settings import AppSettings, build_llm


class StaticTokens:
    def get_token(self) -> str:
        return "entra-token"


def recorder(handler):  # noqa: ANN001, ANN201
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return seen, httpx.MockTransport(wrapped)


ITEM = EnrichmentInput("r1", "Minicode_ Threat Modeling", organizer="Jussi Korhonen",
                       chunks=[{"start": 0, "end": 30, "text": "Jussi: STRIDE time", "speakers": ["Jussi"]}])


def test_azure_openai_chat_sends_strict_json_schema() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "id": "x", "object": "chat.completion", "created": 0, "model": "gpt-4.1-mini-2025-04-14",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": '{"ok": true}'}}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
        })

    seen, transport = recorder(handler)
    llm = AzureOpenAIChat("https://aoai.example.com", "gpt-4.1-mini", api_key="k", http_client=httpx.Client(transport=transport),
                          max_retries=0)
    resp = llm.complete(enrichment_messages(ITEM), json_schema(), SCHEMA_NAME)
    assert resp.text == '{"ok": true}' and resp.input_tokens == 120 and resp.model.startswith("gpt-4.1-mini")
    req = seen[0]
    assert req.url.path == "/openai/deployments/gpt-4.1-mini/chat/completions"
    assert req.url.params["api-version"] == "2024-10-21" and req.headers["api-key"] == "k"
    body = json.loads(req.content)
    assert body["temperature"] == 0 and body["response_format"]["json_schema"]["strict"] is True
    assert body["response_format"]["json_schema"]["name"] == SCHEMA_NAME
    assert "<transcript>" in body["messages"][-1]["content"]


def test_claude_foundry_forces_tool_and_uses_entra_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "model": "claude-sonnet-4-6", "content": [{"type": "tool_use", "name": SCHEMA_NAME, "input": {"title": "T"}}],
            "usage": {"input_tokens": 200, "output_tokens": 40},
        })

    seen, transport = recorder(handler)
    llm = ClaudeFoundryChat("https://res.services.ai.azure.com/", "claude-sonnet-4-6", tokens=StaticTokens(), transport=transport)
    resp = llm.complete(enrichment_messages(ITEM), json_schema(), SCHEMA_NAME)
    assert json.loads(resp.text) == {"title": "T"} and resp.output_tokens == 40
    req = seen[0]
    assert str(req.url) == "https://res.services.ai.azure.com/anthropic/v1/messages"
    assert req.headers["authorization"] == "Bearer entra-token" and req.headers["anthropic-version"] == "2023-06-01"
    body = json.loads(req.content)
    assert body["tool_choice"] == {"type": "tool", "name": SCHEMA_NAME}
    assert body["tools"][0]["input_schema"]["additionalProperties"] is False
    assert all(m["role"] != "system" for m in body["messages"]) and "catalogue" in body["system"].lower()


def test_claude_api_key_mode_and_text_fallback() -> None:
    seen, transport = recorder(lambda r: httpx.Response(200, json={"content": [{"type": "text", "text": '{"a": 1}'}]}))
    llm = ClaudeFoundryChat("https://res.services.ai.azure.com/anthropic", "c", api_key="secret", transport=transport)
    assert llm.complete([{"role": "user", "content": "hi"}], {}, "s").text == '{"a": 1}'
    assert seen[0].headers["x-api-key"] == "secret" and "authorization" not in seen[0].headers


def test_azure_openai_embedder_batches_and_orders() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        data = [{"object": "embedding", "index": i, "embedding": [float(i), float(len(t))]} for i, t in enumerate(body["input"])]
        return httpx.Response(200, json={"object": "list", "model": "te3", "data": list(reversed(data)),
                                         "usage": {"prompt_tokens": 1, "total_tokens": 1}})

    seen, transport = recorder(handler)
    emb = AzureOpenAIEmbedder("https://aoai.example.com", dimensions=2, api_key="k", batch_size=2,
                              http_client=httpx.Client(transport=transport))
    vectors = emb.embed(["a", "bb", "ccc"])
    assert vectors == [[0.0, 1.0], [1.0, 2.0], [0.0, 3.0]] and len(seen) == 2
    assert json.loads(seen[0].content)["dimensions"] == 2


def test_hash_embedder_is_deterministic_and_normalized() -> None:
    e = HashEmbedder(64)
    a, b, c = e.embed(["Bicep modules registry", "bicep module registries", "Kahvihuone ja kakku"])
    assert a == e.embed(["Bicep modules registry"])[0] and len(a) == 64
    assert abs(sum(x * x for x in a) - 1) < 1e-9
    dot = lambda x, y: sum(p * q for p, q in zip(x, y, strict=True))  # noqa: E731
    assert dot(a, b) > dot(a, c)
    assert tokenize("Älä, Bicep!") == ["älä", "bicep"]


@pytest.mark.parametrize(
    ("provider", "name"),
    [("mock", "mock-b"), ("mock-a", "mock-a"), ("azure-openai:gpt-4o", "azure-openai:gpt-4o"),
     ("claude-foundry", "claude-foundry:claude-sonnet-4-6")],
)
def test_build_llm(provider: str, name: str) -> None:
    s = AppSettings(azure_openai_endpoint="https://aoai.example.com", azure_openai_api_key="k",
                    claude_endpoint="https://x.services.ai.azure.com", claude_api_key="k")
    assert build_llm(s, provider).name == name


def test_build_llm_requires_endpoint() -> None:
    with pytest.raises((RuntimeError, ValueError)):
        build_llm(AppSettings(), "azure-openai")
    with pytest.raises((RuntimeError, ValueError)):
        build_llm(AppSettings(), "gemini")

