"""Renderer backed by FFmpeg with libass.

Crops to 9:16, burns in the ASS track, encodes at the settings PRD.md fixes.
Argument lists only — never a shell string.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from clipping.config import (
    AUDIO_BITRATE,
    AUDIO_CODEC,
    CRF,
    OUTPUT_FPS,
    OUTPUT_HEIGHT,
    OUTPUT_WIDTH,
    PRESET,
    VIDEO_CODEC,
    resolve_executable,
)

ProgressCallback = Callable[[float, str], None]

# FFmpeg's -progress stream reports elapsed output time in microseconds.
_OUT_TIME = re.compile(r"out_time_us=(\d+)")


class RenderError(RuntimeError):
    """FFmpeg failed. The message carries its last stderr line."""


class FfmpegRenderer:
    """Cuts, reframes, burns captions, encodes."""

    def __init__(
        self,
        executable: str | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> None:
        self._executable = executable or resolve_executable("ffmpeg")
        self._on_progress = on_progress or (lambda percent, detail: None)

    def render(
        self, video: Path, ass_track: Path, start: float, end: float, destination: Path
    ) -> Path:
        """Render `start`..`end` of `video` with `ass_track` burned in.

        `-ss` sits before `-i` so FFmpeg seeks rather than decoding and
        discarding everything up to the cut. The ASS track is already
        clip-relative, so the burn-in needs no offset of its own.
        """
        destination.parent.mkdir(parents=True, exist_ok=True)
        duration = end - start
        if duration <= 0:
            raise RenderError(f"cannot render a clip of {duration:.2f}s")

        command = [
            self._executable,
            "-hide_banner", "-loglevel", "error", "-y",
            "-progress", "pipe:1", "-nostats",
            "-ss", f"{start:.3f}",
            "-t", f"{duration:.3f}",
            "-i", str(video),
            "-vf", self._filter_chain(ass_track),
            "-r", str(OUTPUT_FPS),
            "-c:v", VIDEO_CODEC,
            "-crf", str(CRF),
            "-preset", PRESET,
            "-pix_fmt", "yuv420p",
            "-c:a", AUDIO_CODEC,
            "-b:a", AUDIO_BITRATE,
            "-movflags", "+faststart",
            str(destination),
        ]
        self._run(command, duration)

        if not destination.exists():
            raise RenderError(f"FFmpeg reported success but {destination} is missing")
        return destination

    def _filter_chain(self, ass_track: Path) -> str:
        """Centre-crop to 9:16, scale to 1080x1920, then burn in the subtitles.

        PRD.md puts subject tracking out of scope, so the crop is a fixed centre
        crop. Captions are burned last so the crop cannot cut them off.
        """
        escaped = self._escape_filter_path(ass_track)
        return (
            f"crop='min(iw,ih*9/16)':'min(ih,iw*16/9)',"
            f"scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:flags=lanczos,"
            f"setsar=1,"
            f"ass='{escaped}'"
        )

    @staticmethod
    def _escape_filter_path(path: Path) -> str:
        """Escape a path for FFmpeg's filtergraph parser.

        On Windows the drive colon and the backslashes both mean something to
        that parser, so `C:\\work\\a.ass` has to become `C\\:/work/a.ass`.
        """
        text = str(path).replace("\\", "/")
        return text.replace(":", "\\:")

    def _run(self, command: list[str], duration: float) -> None:
        """Run FFmpeg, reporting encode progress against the known duration.

        Read line by line rather than waited on: an encode is tens of seconds
        and a blocking call cannot report anything while it runs.
        """
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                # Merged, not a second pipe: draining only stdout while stderr
                # fills its own buffer deadlocks the child. FFmpeg is quiet at
                # loglevel error, but "quiet enough today" is not a guarantee.
                stderr=subprocess.STDOUT,
                text=True,
                shell=False,
            )
        except FileNotFoundError as error:
            raise RenderError(
                f"{self._executable} is not installed or not on PATH"
            ) from error

        collected: list[str] = []
        assert process.stdout is not None
        for line in process.stdout:
            collected.append(line)
            match = _OUT_TIME.search(line)
            if match and duration > 0:
                encoded = int(match.group(1)) / 1_000_000
                self._on_progress(min(encoded / duration * 100.0, 100.0), "")

        process.wait()
        if process.returncode != 0:
            # Progress keys dominate the merged stream, so report the last line
            # that is not one of them.
            noise = ("out_time", "frame=", "fps=", "bitrate=", "total_size",
                     "speed=", "progress=", "stream_", "dup_frames", "drop_frames")
            lines = [
                line.strip() for line in collected
                if line.strip() and not line.startswith(noise)
            ]
            detail = lines[-1] if lines else f"exit code {process.returncode}"
            raise RenderError(f"FFmpeg failed: {detail}")
