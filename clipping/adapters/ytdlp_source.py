"""MediaSource backed by yt-dlp.

Every invocation passes an argument list, never a shell string. A YouTube URL
arrives from a text field the user pasted into; handing that to a shell is
command injection. There is no `shell=True` anywhere in this project.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from clipping.config import WINDOW_PADDING_SECONDS, resolve_executable


class MediaFetchError(RuntimeError):
    """yt-dlp failed. The message carries its last stderr line."""


class YtDlpSource:
    """Fetches audio, and later a single window of video, from YouTube."""

    def __init__(self, executable: str | None = None) -> None:
        self._executable = executable or resolve_executable("yt-dlp")

    def probe_duration(self, url: str) -> float:
        """Read the episode duration without downloading the media."""
        result = self._run(
            [self._executable, "--no-warnings", "--dump-single-json", "--skip-download", url]
        )
        try:
            metadata = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise MediaFetchError(f"yt-dlp returned unparseable metadata: {error}") from error

        duration = metadata.get("duration")
        if duration is None:
            raise MediaFetchError("yt-dlp metadata has no duration; is this a live stream?")
        return float(duration)

    def fetch_audio(self, url: str, destination: Path) -> Path:
        """Audio stream only.

        `-f bestaudio` is what keeps this at tens of megabytes instead of a
        gigabyte. Nothing before the hook is chosen needs the pixels.
        """
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._run(
            [
                self._executable,
                "--no-warnings",
                "-f", "bestaudio",
                "-x", "--audio-format", "wav",
                "--postprocessor-args", "ffmpeg:-ar 16000 -ac 1",
                "-o", str(destination.with_suffix(".%(ext)s")),
                url,
            ]
        )
        produced = destination.with_suffix(".wav")
        if not produced.exists():
            raise MediaFetchError(f"yt-dlp reported success but {produced} is missing")
        return produced

    def fetch_video_window(
        self, url: str, start: float, end: float, destination: Path
    ) -> Path:
        """Fetch only the chosen window, with bounded padding at each end."""
        padded_start = max(start - WINDOW_PADDING_SECONDS, 0.0)
        padded_end = end + WINDOW_PADDING_SECONDS
        destination.parent.mkdir(parents=True, exist_ok=True)

        self._run(
            [
                self._executable,
                "--no-warnings",
                "-f", "bestvideo[height<=1080]+bestaudio/best",
                "--download-sections", f"*{padded_start:.2f}-{padded_end:.2f}",
                "--force-keyframes-at-cuts",
                "--merge-output-format", "mp4",
                "-o", str(destination.with_suffix(".%(ext)s")),
                url,
            ]
        )
        produced = destination.with_suffix(".mp4")
        if not produced.exists():
            raise MediaFetchError(f"yt-dlp reported success but {produced} is missing")
        return produced

    def _run(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                command, capture_output=True, text=True, check=True, shell=False
            )
        except FileNotFoundError as error:
            raise MediaFetchError(
                f"{self._executable} is not installed or not on PATH"
            ) from error
        except subprocess.CalledProcessError as error:
            last_line = (error.stderr or "").strip().splitlines()
            detail = last_line[-1] if last_line else f"exit code {error.returncode}"
            raise MediaFetchError(f"yt-dlp failed: {detail}") from error
