"""Microsoft Graph client for the minicode channel's SharePoint document library.

Teams channel meeting recordings are saved as .mp4 files in the channel folder's `Recordings`
subfolder of the team site's default document library ("Shared Documents/<Channel>/Recordings").
When a meeting was transcribed, a `.vtt` file with the same stem may also be stored next to it
(e.g. a downloaded transcript); otherwise the transcript lives in the Stream media metadata which
needs a different API (see docs/week2-ingestion.md). Recordings without a sidecar transcript go
to Azure AI Speech.

Auth: app-only token for the backend app registration with the `Sites.Selected` application
permission + a `read` grant on this one site. Nothing here needs delegated permissions.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import quote, unquote

import httpx

from minicode.ingestion.http import AzureIdentityTokenProvider, HttpError, RestClient, TokenProvider
from minicode.inventory.models import Recording, RecordingStatus

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPE = "https://graph.microsoft.com/.default"
VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mov", ".webm", ".mkv"}
TRANSCRIPT_EXTENSIONS = (".vtt",)
# sharepointIds is only returned when selected; it carries listItemUniqueId for the Stream embed URL.
ITEM_SELECT = ("id,name,webUrl,createdDateTime,lastModifiedDateTime,createdBy,video,file,folder,size,eTag,cTag,"
               "parentReference,deleted,sharepointIds")


class GraphClient(RestClient):
    def __init__(self, tokens: TokenProvider | None = None, transport: httpx.BaseTransport | None = None, **kwargs: Any) -> None:
        super().__init__(GRAPH_BASE, tokens or AzureIdentityTokenProvider(GRAPH_SCOPE), transport=transport, **kwargs)

    def iter_collection(self, path_or_url: str, params: dict[str, Any] | None = None) -> Iterator[dict[str, Any]]:
        """Yield `value[]` items, following `@odata.nextLink` (which already carries the query)."""
        url: str | None = path_or_url
        while url:
            page = self.get_json(url, params=params)
            params = None
            yield from page.get("value", [])
            url = page.get("@odata.nextLink")

    def delta(self, url: str) -> tuple[list[dict[str, Any]], str]:
        """Drain a delta query; returns (items, deltaLink for the next round)."""
        items: list[dict[str, Any]] = []
        next_url: str | None = url
        while next_url:
            page = self.get_json(next_url)
            items.extend(page.get("value", []))
            if delta_link := page.get("@odata.deltaLink"):
                return items, delta_link
            next_url = page.get("@odata.nextLink")
        raise RuntimeError("delta response ended without @odata.deltaLink")


@dataclass(frozen=True)
class Change:
    recording: Recording
    deleted: bool = False


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _is_video(item: dict[str, Any]) -> bool:
    if "file" not in item:
        return False
    mime = (item["file"].get("mimeType") or "").lower()
    return mime.startswith("video/") or PurePosixPath(item.get("name", "")).suffix.lower() in VIDEO_EXTENSIONS


def _is_transcript(item: dict[str, Any]) -> bool:
    return "file" in item and item.get("name", "").lower().endswith(TRANSCRIPT_EXTENSIONS)


def _item_folder(item: dict[str, Any]) -> str:
    """'/drives/{id}/root:/General/Recordings' -> 'General/Recordings'."""
    path = (item.get("parentReference") or {}).get("path") or ""
    return unquote(path.split("root:", 1)[1].strip("/")) if "root:" in path else ""


def _quote_path(path: str) -> str:
    return quote(path.strip("/"), safe="/")


class GraphRecordingSource:
    """`RecordingSource` over a Teams channel's Recordings folder (backfill + delta).

    `list_recordings(since=...)` walks the folder (recursively), keeps video files created on/after
    `since`, and flags `has_transcript` when a same-stem `.vtt` sits next to the video.
    `latest_cursor()` / `list_changes(cursor)` implement incremental sync with drive delta.
    """

    name = "graph"

    def __init__(
        self,
        site_id: str,
        drive_id: str | None = None,
        folder_path: str = "Recordings",
        client: GraphClient | None = None,
        since: datetime | None = None,
    ) -> None:
        self.site_id = site_id
        self._drive_id = drive_id
        self.folder_path = folder_path.strip("/")
        self._client = client
        self.since = since

    @property
    def client(self) -> GraphClient:
        if self._client is None:
            self._client = GraphClient()
        return self._client

    @property
    def drive_id(self) -> str:
        if not self._drive_id:
            if not self.site_id:
                raise ValueError("MINICODE_SITE_ID (or a drive id) is required for the Graph source")
            self._drive_id = self.client.get_json(f"/sites/{self.site_id}/drive", params={"$select": "id"})["id"]
        return self._drive_id

    # --- backfill -----------------------------------------------------------------------------

    def list_recordings(self, since: datetime | None = None) -> Iterator[Recording]:
        since = since or self.since
        root = f"/drives/{self.drive_id}/root:/{_quote_path(self.folder_path)}:/children"
        yield from self._walk(root, self.folder_path, since)

    def _walk(self, children_url: str, folder: str, since: datetime | None) -> Iterator[Recording]:
        items = list(self.client.iter_collection(children_url, params={"$top": 200, "$select": ITEM_SELECT}))
        transcripts = {PurePosixPath(i["name"]).stem.lower() for i in items if _is_transcript(i)}
        for item in items:
            if "folder" in item:
                sub = f"/drives/{self.drive_id}/items/{item['id']}/children"
                yield from self._walk(sub, f"{folder}/{item['name']}", since)
            elif _is_video(item):
                rec = self._to_recording(item, folder, PurePosixPath(item["name"]).stem.lower() in transcripts)
                if since is None or (rec.recorded_at is not None and rec.recorded_at >= since):
                    yield rec

    def _to_recording(self, item: dict[str, Any], folder: str, has_transcript: bool | None) -> Recording:
        user = (item.get("createdBy") or {}).get("user") or {}
        duration_ms = (item.get("video") or {}).get("duration")
        return Recording(
            id=item["id"],
            title=PurePosixPath(item["name"]).stem,
            status=RecordingStatus.AVAILABLE,
            has_transcript=has_transcript,
            recorded_at=_parse_dt(item.get("createdDateTime")),
            duration_seconds=round(duration_ms / 1000) if duration_ms else None,
            web_url=item.get("webUrl"),
            drive_item_id=item["id"],
            source=self.name,
            organizer=user.get("displayName"),
            organizer_email=user.get("email"),
            etag=item.get("cTag") or item.get("eTag"),
            size_bytes=item.get("size"),
            mime_type=(item.get("file") or {}).get("mimeType"),
            folder_path=folder,
            file_name=item["name"],
            list_item_unique_id=(item.get("sharepointIds") or {}).get("listItemUniqueId"),
        )

    # --- content ------------------------------------------------------------------------------

    def get_transcript(self, recording: Recording) -> str | None:
        """Sidecar `<stem>.vtt` next to the video, or None."""
        folder = recording.folder_path or self.folder_path
        stem = PurePosixPath(recording.file_name or recording.title).stem
        url = f"/drives/{self.drive_id}/root:/{_quote_path(f'{folder}/{stem}.vtt')}:/content"
        try:
            return self.client.request("GET", url).content.decode("utf-8-sig")
        except HttpError as e:
            if e.status_code == 404:
                return None
            raise

    def get_download_url(self, recording: Recording) -> str:
        """Short-lived (~1 h) pre-authenticated URL; ffmpeg can stream from it without a token."""
        item = self.client.get_json(f"/drives/{self.drive_id}/items/{recording.drive_item_id or recording.id}")
        url = item.get("@microsoft.graph.downloadUrl")
        if not url:
            raise RuntimeError(f"no downloadUrl for {recording.id}")
        return url

    # --- incremental (delta) ------------------------------------------------------------------

    def latest_cursor(self) -> str:
        """Delta link representing 'now' (no items), stored before a backfill starts."""
        # $select is kept in the returned deltaLink, so later delta pages also carry sharepointIds.
        _, link = self.client.delta(f"/drives/{self.drive_id}/root/delta?$select={ITEM_SELECT}&token=latest")
        return link

    def list_changes(self, cursor: str) -> tuple[list[Change], str]:
        """Changes since `cursor` within the Recordings folder.

        SharePoint only supports delta on the drive root, so items are filtered by
        `parentReference.path`. Deleted items carry a `deleted` facet and usually no path, so
        they are always reported (the pipeline ignores ids it never ingested). A new/changed
        sidecar `.vtt` is reported as a change of its video so the transcript gets picked up.
        Raises HttpError(410) when the token expired -> caller does a full backfill.
        """
        items, next_cursor = self.client.delta(cursor)
        changes: dict[str, Change] = {}
        transcript_stems: set[tuple[str, str]] = set()
        prefix = self.folder_path.lower()
        for item in items:
            if "deleted" in item:
                changes[item["id"]] = Change(Recording(id=item["id"], title=item.get("name", ""), status=RecordingStatus.DELETED,
                                                       drive_item_id=item["id"], source=self.name), deleted=True)
                continue
            folder = _item_folder(item)
            if not (folder.lower() == prefix or folder.lower().startswith(prefix + "/")):
                continue
            if _is_video(item):
                changes[item["id"]] = Change(self._to_recording(item, folder, None))
            elif _is_transcript(item):
                transcript_stems.add((folder, PurePosixPath(item["name"]).stem))
        for folder, stem in transcript_stems:
            for video in self._videos_with_stem(folder, stem):
                changes[video.id] = Change(video)
        return list(changes.values()), next_cursor

    def _videos_with_stem(self, folder: str, stem: str) -> Iterator[Recording]:
        url = f"/drives/{self.drive_id}/root:/{_quote_path(folder)}:/children"
        for item in self.client.iter_collection(url, params={"$top": 200}):
            if _is_video(item) and PurePosixPath(item["name"]).stem.lower() == stem.lower():
                yield self._to_recording(item, folder, True)
