from __future__ import annotations

import pytest

from minicode.ingestion.chunking import chunk_transcript, estimate_tokens, render, split_long_cue
from minicode.ingestion.fakes import SAMPLES_DIR
from minicode.ingestion.transcripts import Cue, Transcript, parse_vtt


def _transcript(n: int = 60, seconds: float = 10.0, words: int = 12) -> Transcript:
    cues = [
        Cue(i * seconds, i * seconds + seconds - 0.5, " ".join(f"w{i}x{j}" for j in range(words)), "Ann" if (i // 5) % 2 == 0 else "Bob")
        for i in range(n)
    ]
    return Transcript("rec", "teams-vtt", cues)


def test_render_prefixes_speaker_on_change() -> None:
    cues = [Cue(0, 1, "a", "Ann"), Cue(1, 2, "b", "Ann"), Cue(2, 3, "c", "Bob"), Cue(3, 4, "d", None)]
    assert render(cues) == "Ann: a b\nBob: c\nd"


def test_chunks_respect_token_and_time_bounds() -> None:
    t = _transcript()
    chunks = chunk_transcript(t, max_tokens=120, max_seconds=60, overlap_seconds=15)
    assert len(chunks) > 5
    for c in chunks:
        assert c.token_count <= 120
        assert c.end - c.start <= 60
        assert c.speakers
    assert [c.id for c in chunks[:2]] == ["rec-0000", "rec-0001"]
    assert chunks[0].start == 0.0
    assert chunks[-1].end == pytest.approx(t.duration)


def test_every_cue_is_covered_and_overlap_is_bounded() -> None:
    t = _transcript()
    chunks = chunk_transcript(t, max_tokens=120, max_seconds=60, overlap_seconds=15)
    for cue in t.cues:
        assert any(cue.text in c.text for c in chunks)
    for prev, nxt in zip(chunks, chunks[1:], strict=False):
        assert nxt.start >= prev.start  # always progresses
        assert prev.end - nxt.start <= 15 + 10  # overlap: at most the trailing ~15 s of cues
        assert nxt.end > prev.end


def test_no_overlap_option() -> None:
    chunks = chunk_transcript(_transcript(), max_tokens=120, max_seconds=60, overlap_seconds=0)
    for prev, nxt in zip(chunks, chunks[1:], strict=False):
        assert nxt.start >= prev.end


def test_long_cue_is_split_with_interpolated_times() -> None:
    text = "This is one sentence. " * 80
    cue = Cue(100.0, 200.0, text.strip(), "Speaker 1")
    pieces = split_long_cue(cue, max_tokens=60)
    assert len(pieces) > 1
    assert pieces[0].start == 100.0 and pieces[-1].end == pytest.approx(200.0)
    assert all(estimate_tokens(f"Speaker 1: {p.text}") <= 60 for p in pieces)
    chunks = chunk_transcript(Transcript("r", "azure-speech", [cue]), max_tokens=60, max_seconds=600)
    assert all(c.token_count <= 60 for c in chunks)


def test_single_huge_word_does_not_loop() -> None:
    cue = Cue(0, 1, "x" * 1000)
    chunks = chunk_transcript(Transcript("r", "azure-speech", [cue]), max_tokens=50)
    assert len(chunks) == 1 and chunks[0].cue_count == 1


def test_empty_transcript() -> None:
    assert chunk_transcript(Transcript("r", "teams-vtt", [])) == []


def test_custom_token_counter() -> None:
    chunks = chunk_transcript(_transcript(n=10), max_tokens=30, max_seconds=1000, count=lambda s: len(s.split()))
    assert all(c.token_count <= 30 for c in chunks)


def test_sample_transcript_defaults() -> None:
    t = parse_vtt((SAMPLES_DIR / "transcripts" / "bicep-private-registry.vtt").read_text(encoding="utf-8"), "bicep")
    chunks = chunk_transcript(t)
    assert 1 <= len(chunks) <= 3
    assert chunks[0].text.startswith("Aino Virtanen: Hi everyone")
    assert set(chunks[0].speakers) >= {"Aino Virtanen", "Mikael Lindqvist"}
    assert chunks[0].to_dict()["speakers"] == list(chunks[0].speakers)


def test_rejects_tiny_budget() -> None:
    with pytest.raises(ValueError):
        chunk_transcript(_transcript(), max_tokens=5)
