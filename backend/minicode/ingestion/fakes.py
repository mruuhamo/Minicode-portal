"""In-process fakes of the Graph drive API and the Speech batch API (httpx.MockTransport).

They let the *real* GraphRecordingSource / SpeechBatchClient / pipeline run locally and in tests
without Azure. Data comes from `minicode/samples/` (recordings.json, Teams-style .vtt files and
speech scripts). Only the API surface used by this project is emulated:

Graph   GET /sites/{site}/drive, /drives/{d}/root:/{path}:/children|content,
        /drives/{d}/items/{id}[/children], /drives/{d}/root/delta?token=...
        (paging via @odata.nextLink, 401 without bearer token, optional 429 throttling)
Speech  POST /speechtotext/transcriptions:submit, GET/DELETE /speechtotext/transcriptions/{id},
        GET .../{id}/files, result file download (NotStarted -> Running -> Succeeded)
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import parse_qs

import httpx

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"
GRAPH = "https://graph.microsoft.com/v1.0"
DOWNLOAD_BASE = "https://download.mock.local"
SPEECH_ENDPOINT = "https://mock-speech.cognitiveservices.azure.com"
RESULTS_BASE = "https://results.mock.local"
VIDEO_MIME = "video/mp4"
TICKS = 10_000_000


def _json(data: Any, status: int = 200, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, json=data, headers=headers)


def _error(status: int, code: str, message: str = "") -> httpx.Response:
    return _json({"error": {"code": code, "message": message or code}}, status)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class _Job:
    id: str
    display_name: str
    content_urls: list[str]
    locale: str
    body: dict[str, Any]
    polls: int = 0
    status: str = "NotStarted"


@dataclass
class MockCloud:
    now: datetime = field(default_factory=lambda: datetime.now(UTC))
    samples_dir: Path = SAMPLES_DIR
    page_size: int = 3  # small, so paging is exercised
    speech_polls: int = 2  # GETs before a job succeeds
    fail_speech_for: set[str] = field(default_factory=set)  # recording ids whose Speech job fails
    throttle_next: int = 0  # next N Graph requests get 429 + Retry-After

    def __post_init__(self) -> None:
        spec = json.loads((self.samples_dir / "recordings.json").read_text(encoding="utf-8"))
        self.site_id: str = spec["site_id"]
        self.drive_id: str = spec["drive_id"]
        self.folder: str = spec["folder"]
        self.items: dict[str, dict[str, Any]] = {}
        self.content: dict[str, bytes] = {}
        self.speech_scripts: dict[str, Path] = {}
        self.jobs: dict[str, _Job] = {}
        self.requests: list[httpx.Request] = []
        self.version = 0
        self._folder_ids: dict[str, str] = {}
        self._ensure_folder(self.folder)
        for entry in spec["items"]:
            self.add_recording(entry)
        self.version = 0  # initial content is "before" any delta token
        for item in self.items.values():
            item["_version"] = 0

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    # --- content setup / mutation ---------------------------------------------------------------

    @staticmethod
    def make_id(key: str) -> str:
        return "01MOCK" + hashlib.sha1(key.encode()).hexdigest()[:20].upper()

    def _ensure_folder(self, path: str) -> str:
        path = path.strip("/")
        if path in self._folder_ids:
            return self._folder_ids[path]
        parent = str(PurePosixPath(path).parent)
        if parent != ".":
            self._ensure_folder(parent)
        fid = self.make_id(f"folder:{path}")
        self._folder_ids[path] = fid
        self._put(fid, {"name": PurePosixPath(path).name, "folder": {"childCount": 0}}, parent if parent != "." else "")
        return fid

    def _put(self, item_id: str, item: dict[str, Any], folder: str) -> dict[str, Any]:
        self.version += 1
        item.update({
            "id": item_id,
            "parentReference": {
                "driveId": self.drive_id,
                "path": f"/drives/{self.drive_id}/root:" + (f"/{folder}" if folder else ""),
            },
            "eTag": f'"{{{item_id}}},{self.version}"',
            "cTag": f'"c:{{{item_id}}},{self.version}"',
            "_folder": folder,
            "_version": self.version,
        })
        item.setdefault("webUrl", f"https://contoso.sharepoint.com/sites/minicode/Shared%20Documents/{folder}/{item['name']}")
        item.setdefault("sharepointIds", {"listItemUniqueId": str(uuid.uuid5(uuid.NAMESPACE_URL, item_id))})
        self.items[item_id] = item
        return item

    def add_recording(self, entry: dict[str, Any]) -> dict[str, Any]:
        created = self.now - timedelta(days=entry["days_ago"], hours=entry.get("hour_offset", 0))
        created = created.replace(hour=10, minute=1, second=14, microsecond=0)
        ext = entry.get("extension", ".mp4")
        folder = entry.get("folder", self.folder)
        self._ensure_folder(folder)
        is_video = ext == ".mp4"
        stem = f"{entry['stem']}-{created:%Y%m%d_%H%M%S}-Meeting Recording" if is_video else entry["stem"]
        user = {"displayName": entry.get("organizer"), "email": entry.get("email"), "id": self.make_id(entry.get("email", ""))}
        item_id = self.make_id(f"{folder}/{stem}{ext}")
        item: dict[str, Any] = {
            "name": f"{stem}{ext}",
            "createdDateTime": _iso(created),
            "lastModifiedDateTime": _iso(created + timedelta(minutes=5)),
            "createdBy": {"user": user},
            "size": int(entry.get("duration_min", 1) * 60 * 250_000),
            "file": {"mimeType": entry.get("mime", VIDEO_MIME)},
        }
        if is_video:
            item["video"] = {"duration": int(entry.get("duration_min", 1) * 60_000), "width": 1920, "height": 1080}
        self._put(item_id, item, folder)
        self.content[item_id] = f"FAKE-MEDIA:{item_id}".encode()
        if entry.get("transcript"):
            vtt = (self.samples_dir / "transcripts" / entry["transcript"]).read_bytes()
            self.add_transcript(item_id, vtt)
        if entry.get("speech"):
            self.speech_scripts[item_id] = self.samples_dir / "speech" / entry["speech"]
        return self.items[item_id]

    def add_transcript(self, video_id: str, vtt: bytes) -> dict[str, Any]:
        video = self.items[video_id]
        name = PurePosixPath(video["name"]).stem + ".vtt"
        tid = self.make_id(f"{video['_folder']}/{name}")
        self.content[tid] = vtt
        return self._put(tid, {"name": name, "createdDateTime": video["createdDateTime"], "createdBy": video["createdBy"],
                               "size": len(vtt), "file": {"mimeType": "text/vtt"}}, video["_folder"])

    def touch(self, item_id: str) -> None:
        item = self.items[item_id]
        self._put(item_id, item, item["_folder"])

    def delete_item(self, item_id: str) -> None:
        self.version += 1
        self.items[item_id] = {"id": item_id, "deleted": {"state": "deleted"}, "_version": self.version, "_folder": None}

    def video_ids(self) -> list[str]:
        return [i for i, it in self.items.items() if it.get("file", {}).get("mimeType", "").startswith("video/")]

    def find(self, stem_prefix: str) -> str:
        return next(i for i, it in self.items.items() if it.get("name", "").startswith(stem_prefix))

    # --- dispatch -------------------------------------------------------------------------------

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        host = request.url.host
        if host == "graph.microsoft.com":
            return self._graph(request)
        if host == httpx.URL(DOWNLOAD_BASE).host:
            data = self.content.get(request.url.path.strip("/"))
            return httpx.Response(200, content=data) if data is not None else _error(404, "itemNotFound")
        if host == httpx.URL(SPEECH_ENDPOINT).host:
            return self._speech(request)
        if host == httpx.URL(RESULTS_BASE).host:
            return self._speech_result(request.url.path.strip("/").removesuffix(".json"))
        return _error(404, "unknownHost", host)

    # --- Graph ----------------------------------------------------------------------------------

    def _graph(self, request: httpx.Request) -> httpx.Response:
        if not request.headers.get("Authorization", "").startswith("Bearer "):
            return _error(401, "InvalidAuthenticationToken")
        if self.throttle_next > 0:
            self.throttle_next -= 1
            return _json({"error": {"code": "TooManyRequests"}}, 429, {"Retry-After": "1"})
        if request.method != "GET":
            return _error(405, "methodNotAllowed")
        path = request.url.path.removeprefix("/v1.0")
        params = {k: v[0] for k, v in parse_qs(request.url.query.decode()).items()}
        d = re.escape(self.drive_id)
        if m := re.fullmatch(r"/sites/([^/]+)/drive", path):
            return _json({"id": self.drive_id}) if m.group(1) == self.site_id else _error(404, "itemNotFound")
        if m := re.fullmatch(rf"/drives/{d}/root:/(.+):/children", path):
            folder = m.group(1).strip("/")
            if folder not in self._folder_ids:
                return _error(404, "itemNotFound", folder)
            return self._children(folder, request, params)
        if m := re.fullmatch(rf"/drives/{d}/items/([^/]+)/children", path):
            folder = next((p for p, i in self._folder_ids.items() if i == m.group(1)), None)
            return self._children(folder, request, params) if folder is not None else _error(404, "itemNotFound")
        if m := re.fullmatch(rf"/drives/{d}/root:/(.+):/content", path):
            target = m.group(1).strip("/")
            for iid, item in self.items.items():
                if "file" in item and f"{item['_folder']}/{item['name']}" == target:
                    return httpx.Response(200, content=self.content.get(iid, b""))
            return _error(404, "itemNotFound", target)
        if m := re.fullmatch(rf"/drives/{d}/items/([^/]+)", path):
            item = self.items.get(m.group(1))
            if not item or "deleted" in item:
                return _error(404, "itemNotFound")
            return _json({**self._public(item), "@microsoft.graph.downloadUrl": f"{DOWNLOAD_BASE}/{item['id']}"})
        if re.fullmatch(rf"/drives/{d}/root/delta", path):
            return self._delta(params.get("token"))
        return _error(400, "invalidRequest", path)

    @staticmethod
    def _public(item: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in item.items() if not k.startswith("_")}

    def _children(self, folder: str, request: httpx.Request, params: dict[str, str]) -> httpx.Response:
        kids = sorted((i for i in self.items.values() if i.get("_folder") == folder), key=lambda i: i["name"])
        start = int(params.get("$skiptoken", 0))
        page = kids[start : start + self.page_size]
        body: dict[str, Any] = {"value": [self._public(i) for i in page]}
        if start + self.page_size < len(kids):
            body["@odata.nextLink"] = str(request.url.copy_merge_params({"$skiptoken": str(start + self.page_size)}))
        return _json(body)

    def _delta(self, token: str | None) -> httpx.Response:
        link = f"{GRAPH}/drives/{self.drive_id}/root/delta?token=v{self.version}"
        if token == "latest":
            return _json({"value": [], "@odata.deltaLink": link})
        if token is None:
            since = -1
        elif re.fullmatch(r"v\d+", token):
            since = int(token[1:])
        else:
            return _error(410, "resyncRequired", "token expired")
        changed = [self._public(i) for i in self.items.values() if i["_version"] > since]
        return _json({"value": changed, "@odata.deltaLink": link})

    # --- Speech ---------------------------------------------------------------------------------

    def _speech(self, request: httpx.Request) -> httpx.Response:
        if not request.headers.get("Authorization", "").startswith("Bearer "):
            return _error(401, "Unauthorized")
        path = request.url.path
        if request.method == "POST" and path == "/speechtotext/transcriptions:submit":
            body = json.loads(request.content)
            missing = [k for k in ("contentUrls", "locale", "displayName") if not body.get(k)]
            if missing or "timeToLiveHours" not in body.get("properties", {}):
                return _error(400, "InvalidPayload", f"missing {missing or 'properties.timeToLiveHours'}")
            job = _Job(id=self.make_id(f"job:{len(self.jobs)}:{body['displayName']}"), display_name=body["displayName"],
                       content_urls=body["contentUrls"], locale=body["locale"], body=body)
            self.jobs[job.id] = job
            return _json(self._job_json(job), 201)
        m = re.fullmatch(r"/speechtotext/transcriptions/([^/]+)(/files)?", path)
        if not m or m.group(1) not in self.jobs:
            return _error(404, "NotFound")
        job = self.jobs[m.group(1)]
        if request.method == "DELETE":
            del self.jobs[job.id]
            return httpx.Response(204)
        if m.group(2):
            if job.status != "Succeeded":
                return _json({"values": []})
            return _json({"values": [
                {"kind": "TranscriptionReport", "links": {"contentUrl": f"{RESULTS_BASE}/{job.id}.report.json"}},
                {"kind": "Transcription", "links": {"contentUrl": f"{RESULTS_BASE}/{job.id}.json"}},
            ]})
        job.polls += 1
        recording_id = job.display_name.removeprefix("minicode-")
        if job.polls >= self.speech_polls:
            job.status = "Failed" if recording_id in self.fail_speech_for else "Succeeded"
        else:
            job.status = "Running"
        return _json(self._job_json(job))

    def _job_json(self, job: _Job) -> dict[str, Any]:
        url = f"{SPEECH_ENDPOINT}/speechtotext/transcriptions/{job.id}"
        data: dict[str, Any] = {
            "self": url,
            "displayName": job.display_name,
            "locale": job.locale,
            "status": job.status,
            "links": {"files": f"{url}/files"},
            "properties": {k: v for k, v in job.body.get("properties", {}).items()},
        }
        if job.status == "Failed":
            data["properties"]["error"] = {"code": "InvalidData", "message": "Failed to decode audio (mock)."}
        return data

    def _speech_result(self, job_id: str) -> httpx.Response:
        job = self.jobs.get(job_id)
        if not job or job.status != "Succeeded":
            return _error(404, "NotFound")
        recording_id = job.display_name.removeprefix("minicode-")
        script = self.speech_scripts.get(recording_id)
        text = script.read_text(encoding="utf-8") if script else "1|This recording has no sample script."
        return _json(speech_result_from_script(text, job.content_urls[0], job.locale))


def speech_result_from_script(script: str, source: str = "", default_locale: str = "en-US") -> dict[str, Any]:
    """Build a realistic batch transcription result from '<speaker>|<text>' lines (~0.38 s/word)."""
    locale = default_locale
    phrases: list[dict[str, Any]] = []
    t = 1.2
    for line in script.splitlines():
        line = line.strip()
        if line.startswith("#"):
            if m := re.match(r"#\s*locale:\s*(\S+)", line):
                locale = m.group(1)
            continue
        if not line:
            continue
        speaker, _, text = line.partition("|")
        dur = round(len(text.split()) * 0.38, 2)
        phrases.append({
            "recognitionStatus": "Success",
            "channel": 0,
            "speaker": int(speaker),
            "offset": f"PT{t:.2f}S",
            "duration": f"PT{dur:.2f}S",
            "offsetInTicks": round(t * TICKS),
            "durationInTicks": round(dur * TICKS),
            "durationMilliseconds": round(dur * 1000),
            "offsetMilliseconds": round(t * 1000),
            "locale": locale,
            "nBest": [
                {"confidence": 0.91, "lexical": text.lower(), "itn": text.lower(), "maskedITN": text.lower(), "display": text}
            ],
        })
        t = round(t + dur + 0.6, 2)
    return {
        "source": source,
        "timestamp": _iso(datetime.now(UTC)),
        "durationInTicks": round(t * TICKS),
        "duration": f"PT{t:.2f}S",
        "combinedRecognizedPhrases": [{"channel": 0, "display": " ".join(p["nBest"][0]["display"] for p in phrases)}],
        "recognizedPhrases": phrases,
    }
