"""MediaSource backed by yt-dlp.

Every invocation passes an argument list, never a shell string. A YouTube URL
arrives from a text field the user pasted into; handing that to a shell is
command injection. There is no `shell=True` anywhere in this project.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from clipping.config import WINDOW_PADDING_SECONDS, resolve_executable

ProgressCallback = Callable[[float, str], None]

# yt-dlp's own progress line, emitted one per line under --newline.
_PERCENT = re.compile(r"(\d{1,3}(?:\.\d+)?)%")


class MediaFetchError(RuntimeError):
    """yt-dlp failed. The message carries its last stderr line."""


class YtDlpSource:
    """Fetches audio, and later a single window of video, from YouTube."""

    def __init__(
        self,
        executable: str | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> None:
        self._executable = executable or resolve_executable("yt-dlp")
        self._on_progress = on_progress or (lambda percent, detail: None)

    def probe_duration(self, url: str) -> float:
        """Read the episode duration without downloading the media."""
        # subprocess.run drains both pipes concurrently, so it is safe here and
        # keeps stderr out of the JSON on stdout.
        try:
            completed = subprocess.run(
                [self._executable, "--no-warnings", "--dump-single-json", "--skip-download", url],
                capture_output=True,
                text=True,
                shell=False,
            )
        except FileNotFoundError as error:
            raise MediaFetchError(
                f"{self._executable} is not installed or not on PATH"
            ) from error
        if completed.returncode != 0:
            self._raise(completed.stderr or "", completed.returncode)

        try:
            metadata = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise MediaFetchError(f"yt-dlp returned unparseable metadata: {error}") from error

        duration = metadata.get("duration")
        if duration is None:
            raise MediaFetchError("yt-dlp metadata has no duration; is this a live stream?")
        return float(duration)

    def fetch_audio(self, url: str, destination: Path) -> Path:
        """Audio stream only.

        `-f bestaudio` is what keeps this at tens of megabytes instead of a
        gigabyte. Nothing before the hooks are chosen needs the pixels.
        """
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._run(
            [
                self._executable,
                "--no-warnings", "--newline",
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
                "--no-warnings", "--newline",
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

    def _run(self, command: list[str]) -> str:
        """Run yt-dlp, reporting its own percentage as it prints one.

        Output is read line by line rather than waited on, because a blocking
        `subprocess.run` cannot report progress on a download that takes a
        minute — which is exactly when the user most wants to see it.
        """
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                # Merged, not a second pipe. Reading stdout while stderr fills
                # its own 64 KB buffer deadlocks the child: yt-dlp's ffmpeg
                # merge step writes enough to stderr to block forever, and the
                # run hangs with no output and no error.
                stderr=subprocess.STDOUT,
                text=True,
                shell=False,
            )
        except FileNotFoundError as error:
            raise MediaFetchError(
                f"{self._executable} is not installed or not on PATH"
            ) from error

        collected: list[str] = []
        assert process.stdout is not None
        for line in process.stdout:
            collected.append(line)
            match = _PERCENT.search(line)
            if match and "[download]" in line:
                self._on_progress(float(match.group(1)), "")

        process.wait()
        output = "".join(collected)
        if process.returncode != 0:
            self._raise(output, process.returncode)
        return output

    def _raise(self, output: str, returncode: int) -> None:
        """Report the failure, preferring yt-dlp's own ERROR line.

        stdout and stderr are merged while streaming, so the last line is
        usually ffmpeg progress noise rather than the cause.
        """
        lines = [line.strip() for line in output.strip().splitlines() if line.strip()]
        errors = [line for line in lines if line.startswith("ERROR")]
        if errors:
            detail = errors[-1]
        elif lines:
            detail = lines[-1]
        else:
            detail = f"exit code {returncode}"

        # A 403 here almost always means the binary is older than YouTube's
        # current extraction, not that the video is unavailable. Saying so
        # turns a dead end into a one-line fix.
        if "403" in output or "Forbidden" in output:
            detail += (
                f"\n\nThis usually means {self._executable} is out of date — "
                "YouTube changes how it serves media and older builds stop "
                "working. Update it:\n"
                f"    {self._executable} -U"
            )
        raise MediaFetchError(f"yt-dlp failed: {detail}")
