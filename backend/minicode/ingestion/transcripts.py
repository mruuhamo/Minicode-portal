"""Transcript model and parsers (Teams WebVTT, Azure AI Speech batch JSON)."""

from __future__ import annotations

import html
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Cue:
    start: float  # seconds from start of recording
    end: float
    text: str
    speaker: str | None = None


@dataclass
class Transcript:
    recording_id: str
    source: str  # "teams-vtt" | "azure-speech"
    cues: list[Cue] = field(default_factory=list)
    language: str | None = None

    @property
    def duration(self) -> float:
        return max((c.end for c in self.cues), default=0.0)

    @property
    def speakers(self) -> list[str]:
        seen: dict[str, None] = {}
        for c in self.cues:
            if c.speaker:
                seen.setdefault(c.speaker, None)
        return list(seen)

    def to_dict(self) -> dict[str, Any]:
        return {
            "recordingId": self.recording_id,
            "source": self.source,
            "language": self.language,
            "duration": round(self.duration, 3),
            "speakers": self.speakers,
            "cues": [asdict(c) for c in self.cues],
        }


class TranscriptParseError(ValueError):
    pass


# --- WebVTT -----------------------------------------------------------------------------------

_TS = r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})"
_TIMING_RE = re.compile(rf"^\s*{_TS}\s+-->\s+{_TS}(?:\s+.*)?$")
_VOICE_RE = re.compile(r"<v(?:\.[\w.-]+)?\s+([^>]+)>")
_TAG_RE = re.compile(r"</?[^>]+>")


def _seconds(h: str | None, m: str, s: str, frac: str) -> float:
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(frac.ljust(3, "0")) / 1000


def parse_vtt(text: str, recording_id: str = "", language: str | None = None) -> Transcript:
    """Parse WebVTT as produced by Teams/Stream.

    Handles cue identifiers, optional hours, cue settings, NOTE/STYLE/REGION blocks, multi-line
    payloads, `<v Speaker>` voice spans (closing tag optional, one speaker per cue), other inline
    tags and HTML entities. Cues with a malformed timing line or no text are dropped.
    """
    text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*\n", text.strip())
    if not blocks or not blocks[0].startswith("WEBVTT"):
        raise TranscriptParseError("missing WEBVTT header")

    cues: list[Cue] = []
    for block in blocks[1:]:
        lines = block.split("\n")
        if lines[0].startswith(("NOTE", "STYLE", "REGION")):
            continue
        timing_idx = next((i for i, line in enumerate(lines[:2]) if "-->" in line), None)
        if timing_idx is None:
            continue
        m = _TIMING_RE.match(lines[timing_idx])
        if not m:
            continue
        start = _seconds(*m.group(1, 2, 3, 4))
        end = _seconds(*m.group(5, 6, 7, 8))
        payload = "\n".join(lines[timing_idx + 1 :])
        speaker = None
        if v := _VOICE_RE.search(payload):
            speaker = v.group(1).strip()
        body = html.unescape(_TAG_RE.sub("", payload))
        body = re.sub(r"\s+", " ", body).strip()
        if body:
            cues.append(Cue(start=start, end=max(end, start), text=body, speaker=speaker))
    cues.sort(key=lambda c: (c.start, c.end))
    return Transcript(recording_id=recording_id, source="teams-vtt", cues=cues, language=language)


def format_timestamp(seconds: float) -> str:
    ms = round(seconds * 1000)
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def to_vtt(transcript: Transcript) -> str:
    """Render cues as Teams-style WebVTT (used by the mock services)."""
    out = ["WEBVTT", ""]
    for i, c in enumerate(transcript.cues):
        out.append(f"{i:08x}-0000-4000-8000-{i:012x}/{i}-0")
        out.append(f"{format_timestamp(c.start)} --> {format_timestamp(c.end)}")
        body = html.escape(c.text, quote=False)
        out.append(f"<v {c.speaker}>{body}</v>" if c.speaker else body)
        out.append("")
    return "\n".join(out)


# --- Azure AI Speech batch transcription result ----------------------------------------------

TICKS_PER_SECOND = 10_000_000


def parse_speech_result(data: str | bytes | dict[str, Any], recording_id: str = "") -> Transcript:
    """Parse a batch transcription result file (`kind: Transcription`).

    Uses `recognizedPhrases[*]` with `offsetInTicks`/`durationInTicks`, the diarized `speaker`
    number and the best `display` text. Only channel 0 is used (Teams recordings are mixed down).
    """
    if isinstance(data, (str, bytes)):
        data = json.loads(data)
    if not isinstance(data, dict) or "recognizedPhrases" not in data:
        raise TranscriptParseError("not a Speech transcription result (recognizedPhrases missing)")
    cues: list[Cue] = []
    locales: dict[str, int] = {}
    for phrase in data["recognizedPhrases"]:
        if phrase.get("recognitionStatus", "Success") != "Success" or phrase.get("channel", 0) != 0:
            continue
        best = (phrase.get("nBest") or [{}])[0]
        text = (best.get("display") or "").strip()
        if not text:
            continue
        start = phrase.get("offsetInTicks", 0) / TICKS_PER_SECOND
        end = start + phrase.get("durationInTicks", 0) / TICKS_PER_SECOND
        speaker = phrase.get("speaker")
        if loc := phrase.get("locale"):
            locales[loc] = locales.get(loc, 0) + 1
        cues.append(Cue(start=start, end=end, text=text, speaker=f"Speaker {speaker}" if speaker is not None else None))
    cues.sort(key=lambda c: (c.start, c.end))
    language = max(locales, key=locales.__getitem__) if locales else None
    return Transcript(recording_id=recording_id, source="azure-speech", cues=cues, language=language)
