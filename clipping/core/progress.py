"""Progress reporting.

Every number here comes from the tool actually doing the work — yt-dlp's own
percentage, Whisper's segment position, FFmpeg's frame counter. Nothing is
interpolated from a timer. A progress bar that advances on a clock rather than
on work is worse than no bar, because it teaches the user to distrust it.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from typing import Final

from pydantic import BaseModel, Field


class ProgressEvent(BaseModel):
    """One progress update, as the page renders it."""

    stage: str
    label: str  # human phase: downloading, transcribing, scoring, rendering
    detail: str = ""
    stage_percent: float = Field(default=0.0, ge=0.0, le=100.0)
    overall_percent: float = Field(default=0.0, ge=0.0, le=100.0)
    determinate: bool = True
    """False when the underlying tool cannot report a percentage."""


ProgressSink = Callable[[ProgressEvent], None]


# Weights are shares of total wall clock, from measurements on the reference
# machine: survey transcription dominates, the fetches are minor. They are
# rough on purpose — a weight only has to make the bar move at a believable
# rate, and pretending to three decimal places would be false precision.
STAGE_WEIGHTS: Final[dict[str, float]] = {
    "model-download": 0.00,  # one-time, sits outside the run's own work
    "audio-fetch": 0.10,
    "survey": 0.45,
    "hook": 0.10,
    "precise": 0.20,
    "video-fetch": 0.10,
    "captions": 0.01,
    "render": 0.04,
}

STAGE_LABELS: Final[dict[str, str]] = {
    "model-download": "Downloading model",
    "audio-fetch": "Downloading audio",
    "survey": "Transcribing",
    "hook": "Scoring",
    "precise": "Timing words",
    "video-fetch": "Downloading video",
    "captions": "Building captions",
    "render": "Rendering",
}


class ProgressTracker:
    """Turns per-stage percentages into one overall percentage.

    Stages complete in a fixed order, so overall progress is the weight already
    finished plus the current stage's share of its own weight.
    """

    def __init__(self, sink: ProgressSink | None = None) -> None:
        self._sink = sink or (lambda event: None)
        self._completed: set[str] = set()
        self._current: str | None = None
        self._span: tuple[float, float] = (0.0, 100.0)

    def begin(self, stage: str, detail: str = "") -> None:
        self._current = stage
        self._span = (0.0, 100.0)
        self.update(0.0, detail)

    @contextmanager
    def slice(self, index: int, total: int):
        """Confine a stage's reported percentage to one item's share of it.

        Stages that repeat per clip have two progress sources: the adapter,
        which reports 0-100% for the window it is working on, and the loop,
        which knows that window is one of three. Without this, clip 2 reports
        100% and then the loop resets to 66%, and the bar visibly runs
        backwards.
        """
        previous = self._span
        width = 100.0 / max(total, 1)
        self._span = (index * width, (index + 1) * width)
        try:
            yield
        finally:
            self._span = previous

    def update(
        self, stage_percent: float, detail: str = "", determinate: bool = True
    ) -> None:
        if self._current is None:
            return
        clamped = max(0.0, min(stage_percent, 100.0))
        low, high = self._span
        clamped = low + clamped / 100.0 * (high - low)
        self._sink(
            ProgressEvent(
                stage=self._current,
                label=STAGE_LABELS.get(self._current, self._current),
                detail=detail,
                stage_percent=clamped,
                overall_percent=self._overall(clamped),
                determinate=determinate,
            )
        )

    def finish(self, stage: str | None = None) -> None:
        done = stage or self._current
        if done is None:
            return
        self._completed.add(done)
        self._current = done
        self.update(100.0)

    def _overall(self, stage_percent: float) -> float:
        banked = sum(STAGE_WEIGHTS.get(name, 0.0) for name in self._completed)
        current_weight = STAGE_WEIGHTS.get(self._current or "", 0.0)
        if self._current in self._completed:
            current_weight = 0.0
        total = banked + current_weight * (stage_percent / 100.0)
        return round(min(total, 1.0) * 100.0, 1)
