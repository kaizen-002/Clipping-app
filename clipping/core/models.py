"""Domain models.

Every value that crosses a layer boundary is one of these. `rules.md` bans bare
dicts between layers because a dict is an untyped contract.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

# Bounds from PRD.md MVP Scope 3. A clip outside these is not a short.
MIN_CLIP_SECONDS = 15.0
MAX_CLIP_SECONDS = 60.0


class Word(BaseModel):
    """One word with the timing Whisper measured for it.

    The timing is evidence about the audio, not a property of the text. Editing
    `text` does not entitle anyone to invent a new `start`/`end` — see
    `core.editing`.
    """

    text: str
    start: float
    end: float

    @model_validator(mode="after")
    def _end_after_start(self) -> Word:
        if self.end < self.start:
            raise ValueError(f"word {self.text!r} ends ({self.end}) before it starts ({self.start})")
        return self

    @property
    def duration(self) -> float:
        return self.end - self.start


class Segment(BaseModel):
    """A survey-pass transcript segment. Sentence-ish, no word timings.

    Produced by MVP scope 2, which explicitly does not buy word-level timing for
    the whole episode.
    """

    text: str
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


class Transcript(BaseModel):
    """Segment-level transcript of a whole episode."""

    segments: list[Segment]
    language: str = "en"
    source_duration: float

    def covered_seconds(self) -> float:
        """Total seconds of speech covered. Used against the ≥99% acceptance."""
        return sum(segment.duration for segment in self.segments)

    def contains_instant(self, instant: float) -> bool:
        """True when `instant` falls inside a real segment.

        Validation step 4 of the HookCandidate ladder: a timestamp landing in a
        gap between segments was not derived from the transcript, so it is a
        hallucination rather than a judgement call.
        """
        return any(segment.start <= instant <= segment.end for segment in self.segments)


class HookCandidate(BaseModel):
    """One segment the LLM proposes."""

    start_seconds: float
    end_seconds: float
    reason: str = Field(min_length=1)


class HookCandidateList(BaseModel):
    """Exactly what the LLM is contracted to return, and nothing else.

    A list rather than a single candidate: a run returns the top N ranked
    segments. Candidates are validated individually, so one bad entry costs
    that entry rather than the whole generation.
    """

    clips: list[HookCandidate] = Field(min_length=1)


class HookSelection(BaseModel):
    """A validated, clamped hook, plus how we came by it.

    `origin` and `truncated` exist so the UI can be honest about a fallback
    rather than presenting a heuristic guess as a model judgement.
    """

    start: float
    end: float
    reason: str
    origin: str  # "llm" | "llm-retry" | "heuristic"
    truncated: bool = False
    score: float = 0.0
    rank: int = 1

    @property
    def duration(self) -> float:
        return self.end - self.start


class CaptionLine(BaseModel):
    """One on-screen line: up to `caption.max-words-per-line` words."""

    words: list[Word] = Field(min_length=1)

    @property
    def start(self) -> float:
        return self.words[0].start

    @property
    def end(self) -> float:
        return self.words[-1].end

    @property
    def text(self) -> str:
        return " ".join(word.text for word in self.words)


class Clip(BaseModel):
    """The unit the user edits and exports.

    `words` are absolute-time within the source episode, not relative to
    `start`. Keeping one time base avoids a whole class of off-by-offset bugs;
    the renderer rebases once, at the edge.
    """

    source_url: str
    start: float
    end: float
    words: list[Word]
    origin: str
    reason: str
    truncated: bool = False
    score: float = 0.0
    rank: int = 1

    @property
    def duration(self) -> float:
        return self.end - self.start


class ClipSet(BaseModel):
    """The ranked clips one run produced, best first."""

    source_url: str
    clips: list[Clip]

    def ranked(self) -> list[Clip]:
        return sorted(self.clips, key=lambda clip: clip.rank)


class StageTiming(BaseModel):
    """One row of the measured performance budget.

    PRD.md ships estimates and says the first build task is replacing them with
    measurements. This is what gets written to work/run_log.jsonl.
    """

    stage: str
    seconds: float
    detail: str = ""
