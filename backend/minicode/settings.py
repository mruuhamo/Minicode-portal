"""Week 3 app settings (env vars / Function app settings) and component factories.

Defaults are fully local: mock LLM, hash embeddings, JSON catalogue, local search under MINICODE_DATA_DIR.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

from minicode.paths import REPO_ROOT


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _bool(name: str, default: bool) -> bool:
    value = _env(name)
    return default if value is None else value.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class AppSettings:
    environment: str = "local"
    data_dir: Path = field(default_factory=lambda: REPO_ROOT / "out")
    # LLM
    llm_provider: str = "mock"  # mock | mock-a | azure-openai | claude-foundry
    azure_openai_endpoint: str | None = None
    azure_openai_api_version: str = "2024-10-21"
    azure_openai_chat_deployment: str = "gpt-4.1-mini"
    azure_openai_api_key: str | None = None  # local experiments only; use Entra ID in Azure
    claude_endpoint: str | None = None
    claude_deployment: str = "claude-sonnet-4-6"
    claude_api_key: str | None = None
    summary_language: str = "English"
    # embeddings
    embeddings_provider: str = "hash"  # hash | azure-openai
    embedding_deployment: str = "text-embedding-3-large"
    embedding_dimensions: int = 1024
    # catalogue
    repository: str = "local"  # memory | local | cosmos
    cosmos_endpoint: str | None = None
    cosmos_database: str = "minicode"
    cosmos_container: str = "recordings"
    cosmos_audit_container: str = "audit"
    # search
    search_backend: str = "local"  # local | azure
    search_endpoint: str | None = None
    search_index_prefix: str = "minicode"
    semantic_ranker: bool = False
    # auth
    auth_mode: str = "entra"  # entra | dev
    tenant_id: str | None = None
    api_client_id: str | None = None
    admin_role: str = "Learning.Admin"
    read_scope: str = "Learning.Read"
    dev_user: str = "dev.user@localhost"
    dev_roles: tuple[str, ...] = ("Learning.Admin",)

    @classmethod
    def from_env(cls) -> AppSettings:
        d = cls()
        ai_endpoint = _env("AI_SERVICES_ENDPOINT")
        return cls(
            environment=_env("MINICODE_ENVIRONMENT", d.environment) or d.environment,
            data_dir=Path(_env("MINICODE_DATA_DIR") or d.data_dir),
            llm_provider=(_env("LLM_PROVIDER", d.llm_provider) or d.llm_provider).lower(),
            azure_openai_endpoint=_env("AZURE_OPENAI_ENDPOINT", ai_endpoint),
            azure_openai_api_version=_env("AZURE_OPENAI_API_VERSION", d.azure_openai_api_version) or "",
            azure_openai_chat_deployment=_env("AZURE_OPENAI_CHAT_DEPLOYMENT", d.azure_openai_chat_deployment) or "",
            azure_openai_api_key=_env("AZURE_OPENAI_API_KEY"),
            claude_endpoint=_env("CLAUDE_FOUNDRY_ENDPOINT", ai_endpoint),
            claude_deployment=_env("CLAUDE_DEPLOYMENT", d.claude_deployment) or "",
            claude_api_key=_env("CLAUDE_API_KEY"),
            summary_language=_env("SUMMARY_LANGUAGE", d.summary_language) or "",
            embeddings_provider=(_env("EMBEDDINGS_PROVIDER", d.embeddings_provider) or "").lower(),
            embedding_deployment=_env("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", d.embedding_deployment) or "",
            embedding_dimensions=int(_env("EMBEDDING_DIMENSIONS", str(d.embedding_dimensions)) or 1024),
            repository=(_env("MINICODE_REPOSITORY", d.repository) or "").lower(),
            cosmos_endpoint=_env("COSMOS_ENDPOINT"),
            cosmos_database=_env("COSMOS_DATABASE", d.cosmos_database) or "",
            cosmos_container=_env("COSMOS_CONTAINER", d.cosmos_container) or "",
            cosmos_audit_container=_env("COSMOS_AUDIT_CONTAINER", d.cosmos_audit_container) or "",
            search_backend=(_env("SEARCH_BACKEND", d.search_backend) or "").lower(),
            search_endpoint=_env("SEARCH_ENDPOINT"),
            search_index_prefix=_env("SEARCH_INDEX_PREFIX", d.search_index_prefix) or "",
            semantic_ranker=_bool("SEMANTIC_RANKER", d.semantic_ranker),
            auth_mode=(_env("AUTH_MODE", d.auth_mode) or "").lower(),
            tenant_id=_env("AUTH_TENANT_ID", _env("AZURE_TENANT_ID")),
            api_client_id=_env("API_CLIENT_ID"),
            admin_role=_env("AUTH_ADMIN_ROLE", d.admin_role) or "",
            read_scope=_env("AUTH_READ_SCOPE", d.read_scope) or "",
            dev_user=_env("AUTH_DEV_USER", d.dev_user) or "",
            dev_roles=tuple(r.strip() for r in (_env("AUTH_DEV_ROLES", ",".join(d.dev_roles)) or "").split(",") if r.strip()),
        )


class Components:
    """Lazily built, shared components (one instance per Functions worker / CLI run)."""

    def __init__(self, settings: AppSettings, store=None) -> None:  # noqa: ANN001 - BlobStore
        self.settings = settings
        self._store = store

    @cached_property
    def store(self):  # noqa: ANN201
        if self._store is not None:
            return self._store
        from minicode.ingestion.config import Settings, build_store

        return build_store(Settings.from_env())

    @cached_property
    def llm(self):  # noqa: ANN201
        return build_llm(self.settings)

    @cached_property
    def embedder(self):  # noqa: ANN201
        s = self.settings
        if s.embeddings_provider == "hash":
            from minicode.enrichment.embeddings import HashEmbedder

            return HashEmbedder()
        if s.embeddings_provider == "azure-openai":
            from minicode.enrichment.embeddings import AzureOpenAIEmbedder

            if not s.azure_openai_endpoint:
                raise ValueError("EMBEDDINGS_PROVIDER=azure-openai needs AZURE_OPENAI_ENDPOINT or AI_SERVICES_ENDPOINT")
            return AzureOpenAIEmbedder(s.azure_openai_endpoint, s.embedding_deployment, s.embedding_dimensions,
                                       s.azure_openai_api_version, api_key=s.azure_openai_api_key)
        raise ValueError(f"unknown EMBEDDINGS_PROVIDER {s.embeddings_provider!r}")

    @cached_property
    def repository(self):  # noqa: ANN201
        from minicode.enrichment import repository as r

        s = self.settings
        if s.repository == "memory":
            return r.InMemoryRepository()
        if s.repository == "local":
            return r.LocalJsonRepository(s.data_dir / "catalog")
        if s.repository == "cosmos":
            if not s.cosmos_endpoint:
                raise ValueError("MINICODE_REPOSITORY=cosmos needs COSMOS_ENDPOINT")
            return r.CosmosRepository(s.cosmos_endpoint, s.cosmos_database, s.cosmos_container, s.cosmos_audit_container)
        raise ValueError(f"unknown MINICODE_REPOSITORY {s.repository!r}")

    @cached_property
    def search_backend(self):  # noqa: ANN201
        s = self.settings
        if s.search_backend == "local":
            from minicode.search.local import LocalSearchBackend

            return LocalSearchBackend(s.data_dir / "search")
        if s.search_backend == "azure":
            from minicode.search.azure import AzureSearchBackend

            if not s.search_endpoint:
                raise ValueError("SEARCH_BACKEND=azure needs SEARCH_ENDPOINT")
            return AzureSearchBackend(s.search_endpoint)
        raise ValueError(f"unknown SEARCH_BACKEND {s.search_backend!r}")

    @cached_property
    def enricher(self):  # noqa: ANN201
        from minicode.enrichment.enricher import Enricher

        return Enricher(self.llm, summary_language=self.settings.summary_language)

    @cached_property
    def enrichment_pipeline(self):  # noqa: ANN201
        from minicode.enrichment.pipeline import EnrichmentPipeline

        return EnrichmentPipeline(self.store, self.repository, self.enricher)

    @cached_property
    def indexer(self):  # noqa: ANN201
        from minicode.search.indexer import Indexer

        s = self.settings
        return Indexer(self.search_backend, self.repository, self.store, self.embedder, s.search_index_prefix,
                       semantic=s.search_backend == "azure")

    @cached_property
    def search_service(self):  # noqa: ANN201
        from minicode.search.service import SearchService

        s = self.settings
        return SearchService(self.search_backend, self.repository, self.embedder, s.search_index_prefix, s.semantic_ranker)

    @cached_property
    def authenticator(self):  # noqa: ANN201
        from minicode.api.auth import build_authenticator

        return build_authenticator(self.settings)


def build_llm(settings: AppSettings, provider: str | None = None):  # noqa: ANN201
    """LLM client for a provider name: mock / mock-a / mock-b / azure-openai[:deployment] / claude-foundry[:deployment]."""
    from minicode.enrichment import llm

    name = (provider or settings.llm_provider).lower()
    kind, _, deployment = name.partition(":")
    if kind in ("mock", "mock-b"):
        return llm.MockLLM("b")
    if kind == "mock-a":
        return llm.MockLLM("a")
    if kind == "azure-openai":
        if not settings.azure_openai_endpoint:
            raise ValueError("azure-openai needs AZURE_OPENAI_ENDPOINT (or AI_SERVICES_ENDPOINT)")
        return llm.AzureOpenAIChat(settings.azure_openai_endpoint, deployment or settings.azure_openai_chat_deployment,
                                   settings.azure_openai_api_version, api_key=settings.azure_openai_api_key)
    if kind == "claude-foundry":
        if not settings.claude_endpoint:
            raise ValueError("claude-foundry needs CLAUDE_FOUNDRY_ENDPOINT (https://<resource>.services.ai.azure.com)")
        return llm.ClaudeFoundryChat(settings.claude_endpoint, deployment or settings.claude_deployment,
                                     api_key=settings.claude_api_key)
    raise ValueError(f"unknown LLM provider {name!r} (mock, mock-a, azure-openai, claude-foundry)")
