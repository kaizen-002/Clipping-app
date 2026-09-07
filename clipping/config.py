"""Runtime configuration and the encoding settings PRD.md fixes."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from pydantic import BaseModel

PROJECT_ROOT: Final = Path(__file__).resolve().parent.parent

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
OLLAMA_MODEL: Final = "llama3"
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
