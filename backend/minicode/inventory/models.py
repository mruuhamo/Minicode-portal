from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class RecordingStatus(StrEnum):
    AVAILABLE = "available"
    EXPIRED = "expired"  # Teams recording passed its auto-expiration date
    DELETED = "deleted"  # in the site recycle bin / removed
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Recording:
    """A minicode recording as discovered by a RecordingSource."""

    id: str
    title: str
    status: RecordingStatus = RecordingStatus.UNKNOWN
    has_transcript: bool | None = None  # None = not known yet
    recorded_at: datetime | None = None
    duration_seconds: int | None = None
    web_url: str | None = None
    drive_item_id: str | None = None
    source: str = "unknown"
    # Ingestion metadata (week 2). All optional so the title-only mock source still works.
    organizer: str | None = None  # Teams recordings: driveItem.createdBy = whoever started the recording
    organizer_email: str | None = None
    etag: str | None = None  # change detection for idempotent re-runs
    size_bytes: int | None = None
    mime_type: str | None = None
    folder_path: str | None = None
    file_name: str | None = None
    list_item_unique_id: str | None = None  # sharepointIds.listItemUniqueId -> Stream embed URL (week 4)
