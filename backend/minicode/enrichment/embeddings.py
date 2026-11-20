"""Embedding adapter: Azure OpenAI embeddings (Entra auth) and a deterministic hashing mock."""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any, Protocol

import httpx

from minicode.enrichment.llm import COGNITIVE_SCOPE

TOKEN_RE = re.compile(r"[a-z0-9äöå]+")


class Embedder(Protocol):
    name: str
    dimensions: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def stem(token: str) -> str:
    """Crude language-agnostic stemmer (prefix truncation) - good enough for fi + en dev search."""
    return token[:7]


def tokenize(text: str) -> list[str]:
    return [stem(t) for t in TOKEN_RE.findall(text.lower()) if len(t) > 1]


def l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class HashEmbedder:
    """Feature hashing of stemmed unigrams + bigrams. Deterministic, offline, captures lexical overlap only."""

    def __init__(self, dimensions: int = 256) -> None:
        self.dimensions = dimensions
        self.name = f"hash-{dimensions}"

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dimensions
        toks = tokenize(text)
        feats = toks + [f"{a} {b}" for a, b in zip(toks, toks[1:], strict=False)]
        for f in feats:
            h = int.from_bytes(hashlib.blake2b(f.encode(), digest_size=8).digest(), "big")
            vec[h % self.dimensions] += 1.0 if (h >> 63) == 0 else -1.0
        return l2_normalize(vec)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]


class AzureOpenAIEmbedder:
    def __init__(
        self,
        endpoint: str,
        deployment: str = "text-embedding-3-large",
        dimensions: int = 1024,
        api_version: str = "2024-10-21",
        credential: Any = None,
        api_key: str | None = None,
        http_client: httpx.Client | None = None,
        batch_size: int = 64,
    ) -> None:
        from openai import AzureOpenAI

        kwargs: dict[str, Any] = {"api_version": api_version, "azure_endpoint": endpoint, "max_retries": 5}
        if api_key:
            kwargs["api_key"] = api_key
        else:
            from azure.identity import DefaultAzureCredential, get_bearer_token_provider

            kwargs["azure_ad_token_provider"] = get_bearer_token_provider(credential or DefaultAzureCredential(), COGNITIVE_SCOPE)
        if http_client is not None:
            kwargs["http_client"] = http_client
        self._client = AzureOpenAI(**kwargs)
        self.deployment = deployment
        self.dimensions = dimensions
        self.batch_size = batch_size
        self.name = f"azure-openai:{deployment}:{dimensions}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            batch = [t[:24000] or " " for t in texts[i : i + self.batch_size]]
            resp = self._client.embeddings.create(input=batch, model=self.deployment, dimensions=self.dimensions)
            out.extend(d.embedding for d in sorted(resp.data, key=lambda d: d.index))
        return out
