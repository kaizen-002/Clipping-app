"""Runtime configuration and the encoding settings PRD.md fixes."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Final

from pydantic import BaseModel

PROJECT_ROOT: Final = Path(__file__).resolve().parent.parent
BIN_DIR: Final = PROJECT_ROOT / "bin"


def resolve_executable(name: str) -> str:
    """Find a tool in the project's own bin/ first, then on PATH.

    Bundling the binaries beside the project means a working checkout does not
    depend on what happens to be installed system-wide, which is the usual
    reason "it runs on my machine" stops being true.
    """
    for candidate in (BIN_DIR / f"{name}.exe", BIN_DIR / name):
        if candidate.exists():
            return str(candidate)
    found = shutil.which(name)
    if found:
        return found
    return name  # let the adapter raise a message naming the missing tool

# Encoding is fixed so output size is a stated consequence rather than an
# unmeasurable target. PRD.md "Encoding Settings".
VIDEO_CODEC: Final = "libx264"
CRF: Final = 20
PRESET: Final = "medium"
AUDIO_CODEC: Final = "aac"
AUDIO_BITRATE: Final = "192k"
OUTPUT_WIDTH: Final = 1080
OUTPUT_HEIGHT: Final = 1920
OUTPUT_FPS: Final = 30

# Retention. Without this, hour-long downloads accumulate until the disk fills.
INPUT_MAX_AGE_DAYS: Final = 7
INPUT_MAX_BYTES: Final = 5 * 1024**3  # 5 GB

OLLAMA_HOST: Final = "http://127.0.0.1:11434"
# Qwen 2.5 is markedly stronger than Llama 3 8B on non-English text, which
# matters now that the transcript it reasons over is Indonesian.
OLLAMA_MODEL: Final = "qwen2.5:14b"

# The transcriber detects the audio's language and refuses when it disagrees
# with this, because assuming produced fluent English nonsense from Indonesian
# audio and every clip built on it was meaningless.
TRANSCRIBE_LANGUAGE: Final = "id"

SURVEY_MODEL: Final = "base"
PRECISE_MODEL: Final = "medium"
WINDOW_PADDING_SECONDS: Final = 2.0


class Paths(BaseModel):
    """Where the run keeps its files."""

    input_dir: Path
    output_dir: Path
    work_dir: Path

    @classmethod
    def under(cls, root: Path) -> Paths:
        return cls(
            input_dir=root / "input",
            output_dir=root / "output",
            work_dir=root / "work",
        )

    def ensure(self) -> Paths:
        for directory in (self.input_dir, self.output_dir, self.work_dir):
            directory.mkdir(parents=True, exist_ok=True)
        return self


DEFAULT_PATHS: Final = Paths.under(PROJECT_ROOT)
