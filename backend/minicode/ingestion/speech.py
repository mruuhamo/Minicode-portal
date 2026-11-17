"""Azure AI Speech batch transcription client (REST API v3.2+/2024-11-15).

Flow: submit a job pointing at an audio blob (read SAS URL) -> poll `status` -> list result files
-> download the `Transcription` file (its contentUrl is a pre-authenticated SAS, no token) -> delete
the job. Auth is Entra ID: the Function App managed identity needs the `Cognitive Services
Speech User` role on the AI Services account, and the endpoint must be the custom subdomain
(https://<name>.cognitiveservices.azure.com), which infra/modules/ai.bicep provisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from minicode.ingestion.http import AzureIdentityTokenProvider, RestClient, TokenProvider

SPEECH_SCOPE = "https://cognitiveservices.azure.com/.default"
API_VERSION = "2024-11-15"

SUCCEEDED = "Succeeded"
FAILED = "Failed"
TERMINAL = {SUCCEEDED, FAILED}


@dataclass(frozen=True)
class SpeechOptions:
    locale: str = "fi-FI"  # required by the API; also the fallback when language id is unsure
    candidate_locales: tuple[str, ...] = ("fi-FI", "en-US")  # minicodes are Finnish or English
    diarization: bool = True
    max_speakers: int = 6
    word_timestamps: bool = False
    time_to_live_hours: int = 48  # service deletes the job + results afterwards (6 h..31 d)
    extra_properties: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SpeechJob:
    url: str  # the job's `self` link (used as its id)
    status: str
    error: str | None = None

    @property
    def done(self) -> bool:
        return self.status in TERMINAL


class SpeechBatchClient:
    def __init__(
        self,
        endpoint: str,
        tokens: TokenProvider | None = None,
        transport: httpx.BaseTransport | None = None,
        options: SpeechOptions | None = None,
        api_version: str = API_VERSION,
        **kwargs: Any,
    ) -> None:
        if not endpoint:
            raise ValueError("AI_SERVICES_ENDPOINT is required for Azure AI Speech")
        self.rest = RestClient(endpoint, tokens or AzureIdentityTokenProvider(SPEECH_SCOPE), transport=transport, **kwargs)
        self.options = options or SpeechOptions()
        self.api_version = api_version

    def build_request(self, content_url: str, display_name: str) -> dict[str, Any]:
        o = self.options
        properties: dict[str, Any] = {
            "timeToLiveHours": o.time_to_live_hours,
            "wordLevelTimestampsEnabled": o.word_timestamps,
            "punctuationMode": "DictatedAndAutomatic",
            "profanityFilterMode": "None",
        }
        if len(o.candidate_locales) > 1:
            properties["languageIdentification"] = {"candidateLocales": list(o.candidate_locales), "mode": "Single"}
        if o.diarization:
            properties["diarization"] = {"enabled": True, "maxSpeakers": o.max_speakers}
        properties.update(o.extra_properties)
        return {"contentUrls": [content_url], "locale": o.locale, "displayName": display_name, "properties": properties}

    def submit(self, content_url: str, display_name: str) -> SpeechJob:
        body = self.build_request(content_url, display_name)
        r = self.rest.request("POST", "/speechtotext/transcriptions:submit", params={"api-version": self.api_version}, json=body)
        return self._job(r.json())

    def get(self, job_url: str) -> SpeechJob:
        return self._job(self.rest.get_json(job_url))

    def fetch_result(self, job_url: str) -> dict[str, Any]:
        job = self.rest.get_json(job_url)
        files_url = job["links"]["files"]
        for f in self._iter_files(files_url):
            if f.get("kind") == "Transcription":
                return self.rest.get_json(f["links"]["contentUrl"], auth=False)
        raise RuntimeError(f"no Transcription result file for {job_url}")

    def delete(self, job_url: str) -> None:
        self.rest.request("DELETE", job_url)

    def _iter_files(self, url: str | None):  # type: ignore[no-untyped-def]
        while url:
            page = self.rest.get_json(url)
            yield from page.get("values", [])
            url = page.get("@nextLink")

    @staticmethod
    def _job(data: dict[str, Any]) -> SpeechJob:
        error = None
        if data.get("status") == FAILED:
            err = (data.get("properties") or {}).get("error") or {}
            error = f"{err.get('code', 'Failed')}: {err.get('message', '')}".strip()
        return SpeechJob(url=data["self"], status=data.get("status", "NotStarted"), error=error)
