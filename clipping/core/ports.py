"""The four ports.

`rules.md` closes this list at four: MediaSource, Transcriber, HookFinder,
Renderer. They exist because the core must be testable without a network, a
Whisper model, an LLM or FFmpeg — not because a second implementation is
imagined. A fifth port needs a recorded decision.

HookFinder genuinely has two implementations today (Ollama, and the
deterministic heuristic the fallback path requires), so it would earn its place
under the plain Open/Closed reading too.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from clipping.core.models import HookCandidate, Transcript, Word


class MediaSource(Protocol):
    """Fetches audio and video from the source host."""

    def fetch_audio(self, url: str, destination: Path) -> Path:
        """Fetch the audio stream only. No video stream may be fetched here."""
        ...

    def fetch_video_window(
        self, url: str, start: float, end: float, destination: Path
    ) -> Path:
        """Fetch only `start`..`end`, with at most 2 s of padding each side."""
        ...

    def probe_duration(self, url: str) -> float:
        """Episode duration in seconds, without downloading the media."""
        ...


class Transcriber(Protocol):
    """Speech to text, in the two passes the pipeline needs."""

    def survey(self, audio: Path) -> Transcript:
        """Whole episode, segment-level. Word timings are not required."""
        ...

    def precise(self, audio: Path, start: float, end: float) -> list[Word]:
        """One window, word-level. Returned times are absolute within the episode."""
        ...


class HookFinder(Protocol):
    """Chooses the segment worth clipping."""

    def find(self, transcript: Transcript) -> HookCandidate:
        """Return a candidate, or raise. Validation is the caller's job."""
        ...


class Renderer(Protocol):
    """Burns captions into video."""

    def render(
        self, video: Path, ass_track: Path, start: float, end: float, destination: Path
    ) -> Path:
        """Cut to `start`..`end`, burn in `ass_track`, write an MP4."""
        ...
