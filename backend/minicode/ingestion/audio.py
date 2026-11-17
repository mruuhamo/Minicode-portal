"""Audio extraction for recordings that need Azure AI Speech.

Speech batch transcription accepts audio formats (WAV/MP3/OGG/FLAC/M4A/...), not .mp4 video, and
a 1 h Teams recording is hundreds of MB while 16 kHz mono AAC is ~20 MB. ffmpeg reads straight
from the Graph `downloadUrl`, so the video is never held in memory or written to disk.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Protocol

import httpx

AUDIO_CONTENT_TYPE = "audio/mp4"
AUDIO_EXTENSION = "m4a"


class AudioExtractor(Protocol):
    def extract(self, source_url: str) -> bytes: ...


def find_ffmpeg() -> str | None:
    if exe := shutil.which("ffmpeg"):
        return exe
    try:  # optional dependency that bundles a static ffmpeg binary
        import imageio_ffmpeg  # type: ignore[import-not-found]

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


class FfmpegAudioExtractor:
    def __init__(self, ffmpeg: str | None = None, sample_rate: int = 16000, bitrate: str = "48k", timeout: float = 1800) -> None:
        self.ffmpeg = ffmpeg or find_ffmpeg()
        self.sample_rate = sample_rate
        self.bitrate = bitrate
        self.timeout = timeout

    def command(self, source_url: str, out_file: Path) -> list[str]:
        if not self.ffmpeg:
            raise RuntimeError("ffmpeg not found: install it or `pip install imageio-ffmpeg`")
        return [
            self.ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-i", source_url,
            "-vn", "-ac", "1", "-ar", str(self.sample_rate), "-c:a", "aac", "-b:a", self.bitrate,
            str(out_file),
        ]  # fmt: skip

    def extract(self, source_url: str) -> bytes:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / f"audio.{AUDIO_EXTENSION}"
            proc = subprocess.run(self.command(source_url, out), capture_output=True, timeout=self.timeout, check=False)
            if proc.returncode != 0:
                raise RuntimeError(f"ffmpeg failed ({proc.returncode}): {proc.stderr.decode(errors='replace')[-500:]}")
            return out.read_bytes()


class DownloadAudioExtractor:
    """Downloads the source as-is (mock mode / sources that already are audio)."""

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self.transport = transport

    def extract(self, source_url: str) -> bytes:
        with httpx.Client(transport=self.transport, follow_redirects=True, timeout=300) as http:
            r = http.get(source_url)
            r.raise_for_status()
            return r.content
