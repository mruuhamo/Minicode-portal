"""Build the ingestion pipeline from environment settings (Function App app settings / CLI)."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from minicode.ingestion.audio import AudioExtractor, DownloadAudioExtractor, FfmpegAudioExtractor
from minicode.ingestion.fakes import SPEECH_ENDPOINT, MockCloud
from minicode.ingestion.graph import GraphClient, GraphRecordingSource
from minicode.ingestion.http import StaticTokenProvider
from minicode.ingestion.pipeline import IngestionPipeline, PipelineConfig
from minicode.ingestion.speech import SpeechBatchClient, SpeechOptions
from minicode.paths import REPO_ROOT
from minicode.storage import AzureBlobStore, BlobStore, LocalBlobStore


@dataclass
class Settings:
    source: str = "mock"  # mock (fake Graph+Speech over samples) | graph
    storage: str = "local"  # local | azure
    local_root: Path = field(default_factory=lambda: REPO_ROOT / "out" / "blob")
    blob_endpoint: str = ""
    site_id: str = ""
    drive_id: str | None = None
    folder: str = "General/Recordings"
    speech: str = "auto"  # auto | azure | off ("auto": azure when an endpoint is set; mock in mock mode)
    ai_endpoint: str = ""
    speech_locale: str = "fi-FI"
    candidate_locales: tuple[str, ...] = ("fi-FI", "en-US")
    lookback_days: int = 365

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        default = cls()
        return cls(
            source=env.get("MINICODE_SOURCE", default.source).lower(),
            storage=env.get("MINICODE_STORAGE", default.storage).lower(),
            local_root=Path(env["MINICODE_LOCAL_STORE"]) if env.get("MINICODE_LOCAL_STORE") else default.local_root,
            blob_endpoint=env.get("STORAGE_BLOB_ENDPOINT", ""),
            site_id=env.get("MINICODE_SITE_ID", ""),
            drive_id=env.get("MINICODE_DRIVE_ID") or None,
            folder=env.get("MINICODE_FOLDER_PATH", default.folder),
            speech=env.get("MINICODE_SPEECH", default.speech).lower(),
            ai_endpoint=env.get("AI_SERVICES_ENDPOINT", ""),
            speech_locale=env.get("SPEECH_LOCALE", default.speech_locale),
            candidate_locales=tuple(
                x.strip() for x in env.get("SPEECH_CANDIDATE_LOCALES", "fi-FI,en-US").split(",") if x.strip()
            ),
            lookback_days=int(env.get("BACKFILL_LOOKBACK_DAYS", default.lookback_days)),
        )


def build_store(s: Settings) -> BlobStore:
    if s.storage == "azure":
        if not s.blob_endpoint:
            raise ValueError("STORAGE_BLOB_ENDPOINT is required when MINICODE_STORAGE=azure")
        return AzureBlobStore(s.blob_endpoint)
    if s.storage == "local":
        return LocalBlobStore(s.local_root)
    raise ValueError(f"unknown MINICODE_STORAGE {s.storage!r}")


def build_pipeline(
    s: Settings,
    *,
    store: BlobStore | None = None,
    config: PipelineConfig | None = None,
    cloud: MockCloud | None = None,
    clock: Callable[[], datetime] | None = None,
    audio: AudioExtractor | None = None,
) -> IngestionPipeline:
    clock = clock or (lambda: datetime.now(UTC))
    config = config or PipelineConfig()
    config.lookback_days = s.lookback_days
    store = store or build_store(s)
    options = SpeechOptions(locale=s.speech_locale, candidate_locales=s.candidate_locales)
    speech: SpeechBatchClient | None = None

    if s.source == "mock":
        cloud = cloud or MockCloud(now=clock())
        client = GraphClient(StaticTokenProvider(), transport=cloud.transport, sleep=lambda _: None)
        source = GraphRecordingSource(cloud.site_id, folder_path=cloud.folder, client=client)
        if s.speech != "off":
            speech = SpeechBatchClient(SPEECH_ENDPOINT, StaticTokenProvider(), transport=cloud.transport, options=options)
            audio = audio or DownloadAudioExtractor(cloud.transport)
    elif s.source == "graph":
        source = GraphRecordingSource(s.site_id, drive_id=s.drive_id, folder_path=s.folder)
        if s.speech == "azure" or (s.speech == "auto" and s.ai_endpoint):
            speech = SpeechBatchClient(s.ai_endpoint, options=options)
            audio = audio or FfmpegAudioExtractor()
    else:
        raise ValueError(f"unknown MINICODE_SOURCE {s.source!r}")

    return IngestionPipeline(source, store, speech=speech, audio=audio if speech else None, config=config, clock=clock)
