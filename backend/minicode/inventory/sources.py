"""Recording sources.

`RecordingSource` is the adapter interface used by inventory, backfill and (later) the
change-notification/delta ingestion. Week 1 ships a mock source backed by the title
list; `GraphRecordingSource` is a stub that documents the real implementation.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path
from typing import Protocol, runtime_checkable

from minicode.inventory.models import Recording, RecordingStatus
from minicode.paths import TITLES_FILE


@runtime_checkable
class RecordingSource(Protocol):
    name: str

    def list_recordings(self) -> Iterator[Recording]: ...


def _bucket(text: str, salt: str) -> int:
    """Deterministic 0-99 bucket so mock data is stable between runs."""
    return int(hashlib.sha256(f"{salt}:{text}".encode()).hexdigest(), 16) % 100


class MockRecordingSource:
    """Reads recording titles from a text file (one per line) and fakes Graph metadata.

    Transcript availability and status are SIMULATED (deterministic per title) so that the
    inventory report and downstream code paths can be exercised before Graph access exists.
    """

    name = "mock"

    def __init__(
        self,
        titles_file: Path = TITLES_FILE,
        transcript_rate: int = 60,
        expired_rate: int = 5,
        deleted_rate: int = 2,
    ) -> None:
        self.titles_file = Path(titles_file)
        self.transcript_rate = transcript_rate
        self.expired_rate = expired_rate
        self.deleted_rate = deleted_rate

    def list_recordings(self) -> Iterator[Recording]:
        lines = self.titles_file.read_text(encoding="utf-8").splitlines()
        for index, title in enumerate(line for line in lines if line.strip()):
            key = f"{index}:{title}"
            status_bucket = _bucket(key, "status")
            if status_bucket < self.deleted_rate:
                status = RecordingStatus.DELETED
            elif status_bucket < self.deleted_rate + self.expired_rate:
                status = RecordingStatus.EXPIRED
            else:
                status = RecordingStatus.AVAILABLE
            yield Recording(
                id=f"mock-{index + 1:04d}",
                title=title,
                status=status,
                has_transcript=_bucket(key, "transcript") < self.transcript_rate,
                source=self.name,
            )


class GraphRecordingSource:
    """Microsoft Graph implementation (NOT IMPLEMENTED - waiting for Sites.Selected access).

    Planned implementation:
      * Auth: app-only token for the backend app registration (certificate or managed-identity
        federated credential), Graph application permission `Sites.Selected` with a `read` grant
        on the minicode channel SharePoint site only.
      * Discovery: GET /sites/{site-id}/drives -> the channel's document library, then
        GET /drives/{drive-id}/root:/{channel-folder}/Recordings:/children (or /delta for
        incremental sync) filtered to video files (file.mimeType == "video/mp4").
      * Metadata: createdDateTime, video.duration, webUrl, size, lastModifiedBy.
      * Status: items in the recycle bin -> DELETED; Teams recording expiration date
        (`media` facet / list item field) in the past -> EXPIRED.
      * Transcripts: Stream stores Teams transcripts inside the video's media metadata, not as
        separate files. Whether Sites.Selected is enough to read them must be verified
        (see docs/week1-checklist.md). Fallbacks: onlineMeeting transcripts API
        (OnlineMeetingTranscript.Read.All) or Azure AI Speech transcription.
    """

    name = "graph"

    def __init__(self, site_id: str, drive_id: str | None = None, folder_path: str = "Recordings") -> None:
        self.site_id = site_id
        self.drive_id = drive_id
        self.folder_path = folder_path

    def list_recordings(self) -> Iterator[Recording]:
        raise NotImplementedError(
            "GraphRecordingSource needs Graph Sites.Selected access; use MockRecordingSource until then."
        )
