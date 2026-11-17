"""Split transcripts into time-windowed, token-bounded chunks for embedding and search.

Each chunk keeps the start/end timestamps (deep links into the video) and the speakers.
Defaults suit `text-embedding-3-large` + AI Search hybrid retrieval: ~400 tokens, at most
3 minutes, with ~15 s of overlap so a sentence cut at a boundary is searchable from both sides.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from minicode.ingestion.transcripts import Cue, Transcript

TokenCounter = Callable[[str], int]


def estimate_tokens(text: str) -> int:
    """~4 characters per token (cl100k/o200k average for English/Finnish prose). Swap in tiktoken later."""
    return max(1, math.ceil(len(text) / 4)) if text else 0


@dataclass(frozen=True)
class Chunk:
    id: str
    recording_id: str
    index: int
    start: float
    end: float
    text: str
    speakers: tuple[str, ...]
    token_count: int
    cue_count: int

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["speakers"] = list(self.speakers)
        return d


def render(cues: list[Cue]) -> str:
    """Join cues, prefixing the speaker name whenever it changes ("Name: ...")."""
    lines: list[str] = []
    current: str | None = None
    for c in cues:
        if lines and c.speaker == current:
            lines[-1] += " " + c.text
        else:
            current = c.speaker
            lines.append(f"{c.speaker}: {c.text}" if c.speaker else c.text)
    return "\n".join(lines)


_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def split_long_cue(cue: Cue, max_tokens: int, count: TokenCounter = estimate_tokens) -> list[Cue]:
    """Split a cue whose text exceeds max_tokens (Speech phrases can be long) at sentence, then
    word boundaries; timestamps are interpolated by character position."""
    label = len(f"{cue.speaker}: ") if cue.speaker else 0
    budget = max_tokens - math.ceil(label / 4) - 1
    if count(cue.text) <= budget:
        return [cue]
    pieces: list[str] = []
    buf = ""
    for unit in (w for s in _SENTENCE_RE.split(cue.text) for w in _units(s, budget, count)):
        candidate = f"{buf} {unit}".strip()
        if buf and count(candidate) > budget:
            pieces.append(buf)
            buf = unit
        else:
            buf = candidate
    if buf:
        pieces.append(buf)
    total = sum(len(p) for p in pieces) or 1
    out: list[Cue] = []
    t = cue.start
    for p in pieces:
        dt = (cue.end - cue.start) * len(p) / total
        out.append(Cue(start=t, end=t + dt, text=p, speaker=cue.speaker))
        t += dt
    return out


def _units(sentence: str, budget: int, count: TokenCounter) -> list[str]:
    return [sentence] if count(sentence) <= budget else sentence.split()


def chunk_transcript(
    transcript: Transcript,
    *,
    max_tokens: int = 400,
    max_seconds: float = 180.0,
    overlap_seconds: float = 15.0,
    count: TokenCounter = estimate_tokens,
) -> list[Chunk]:
    if max_tokens < 20:
        raise ValueError("max_tokens must be >= 20")
    cues = [piece for c in transcript.cues for piece in split_long_cue(c, max_tokens, count)]

    groups: list[list[Cue]] = []
    current: list[Cue] = []

    def fits(candidate: list[Cue]) -> bool:
        return count(render(candidate)) <= max_tokens and candidate[-1].end - candidate[0].start <= max_seconds

    for cue in cues:
        if current and not fits([*current, cue]):
            groups.append(current)
            tail = [c for c in current if c.start >= current[-1].end - overlap_seconds] if overlap_seconds > 0 else []
            if len(tail) >= len(current):  # overlap must never repeat a whole chunk
                tail = tail[1:]
            current = tail if tail and fits([*tail, cue]) else []
        current.append(cue)
    if current and (not groups or current[-1] is not groups[-1][-1]):
        groups.append(current)

    chunks: list[Chunk] = []
    for i, group in enumerate(groups):
        text = render(group)
        chunks.append(
            Chunk(
                id=f"{transcript.recording_id}-{i:04d}",
                recording_id=transcript.recording_id,
                index=i,
                start=round(group[0].start, 3),
                end=round(max(c.end for c in group), 3),
                text=text,
                speakers=tuple(dict.fromkeys(c.speaker for c in group if c.speaker)),
                token_count=count(text),
                cue_count=len(group),
            )
        )
    return chunks
