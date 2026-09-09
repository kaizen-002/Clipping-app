"""Hook validation ladder and the deterministic fallback.

Pure functions over values. No network, no model — the ladder is the part most
worth testing and it must be testable without Ollama running.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from clipping.core.models import (
    MAX_CLIP_SECONDS,
    MIN_CLIP_SECONDS,
    HookCandidate,
    HookSelection,
    Transcript,
)


# Clips must come from genuinely different moments. Adjacency is not overlap:
# a model asked for three clips will happily return 1276-1301 and 1301-1325,
# which pass an overlap test and are one continuous stretch of talk.
MIN_GAP_SECONDS = 20.0


def conflicts_with(
    start: float, end: float, taken: list[tuple[float, float]], min_gap: float = MIN_GAP_SECONDS
) -> bool:
    """True when this window overlaps, or sits too close to, one already kept."""
    return any(
        start < taken_end + min_gap and end > taken_start - min_gap
        for taken_start, taken_end in taken
    )


class HookRejected(Exception):
    """A candidate failed the ladder. The message names which rung and why."""


@dataclass(frozen=True)
class ValidationOutcome:
    """A candidate that survived, plus whether rung 3 had to truncate it."""

    start: float
    end: float
    truncated: bool


def validate_candidate(
    candidate: HookCandidate, transcript: Transcript
) -> ValidationOutcome:
    """Run the PRD's four-rung ladder.

    Rung 1 (parses, matches the model) is enforced by Pydantic before we get
    here. Any failure raises rather than being nudged into shape, so a bad
    generation reaches the fallback instead of silently producing a bad clip.
    """
    duration = transcript.source_duration

    # Rung 2 — inside the episode, and pointing forwards.
    if candidate.start_seconds < 0 or candidate.end_seconds > duration:
        raise HookRejected(
            f"span {candidate.start_seconds:.1f}–{candidate.end_seconds:.1f}s "
            f"falls outside the episode (0–{duration:.1f}s)"
        )
    if candidate.start_seconds >= candidate.end_seconds:
        raise HookRejected(
            f"start {candidate.start_seconds:.1f}s is not before "
            f"end {candidate.end_seconds:.1f}s"
        )

    # Rung 3 — length. Too long is truncated and marked; too short is rejected,
    # because padding a short hook invents content the model did not choose.
    start = candidate.start_seconds
    end = candidate.end_seconds
    truncated = False
    if (end - start) > MAX_CLIP_SECONDS:
        end = start + MAX_CLIP_SECONDS
        truncated = True
    if (end - start) < MIN_CLIP_SECONDS:
        raise HookRejected(
            f"span is {end - start:.1f}s, shorter than the {MIN_CLIP_SECONDS:.0f}s minimum"
        )

    # Rung 4 — both ends land in real speech. A timestamp in a gap between
    # segments was not read off the transcript.
    if not transcript.contains_instant(start):
        raise HookRejected(f"start {start:.1f}s falls in a gap, not a transcript segment")
    if not transcript.contains_instant(end):
        raise HookRejected(f"end {end:.1f}s falls in a gap, not a transcript segment")

    return ValidationOutcome(start=start, end=end, truncated=truncated)


# --- Deterministic fallback -------------------------------------------------
#
# Scored scan of the survey transcript, per PRD.md. It is not trying to beat the
# LLM; it exists so the pipeline never dead-ends on a bad generation.

_QUESTION = re.compile(r"\?")
_LAUGHTER = re.compile(r"\[(laughter|laughs|laughing)\]|\(laughs?\)", re.IGNORECASE)
_HOOK_PHRASES = re.compile(
    r"\b(the thing is|here's the|what most people|nobody tells you|the truth is|"
    r"i realised|i realized|the secret|turns out|crazy thing|biggest mistake)\b",
    re.IGNORECASE,
)


def score_window(segments_text: str, duration: float) -> float:
    """Score a candidate window. Higher is more hook-like.

    Speech density carries the base signal: a window dense with words is someone
    making a point, and a sparse one is usually a pause or filler.
    """
    if duration <= 0:
        return 0.0
    word_count = len(segments_text.split())
    density = word_count / duration  # words per second

    score = density
    score += 0.55 * len(_QUESTION.findall(segments_text))
    score += 0.85 * len(_LAUGHTER.findall(segments_text))
    score += 1.30 * len(_HOOK_PHRASES.findall(segments_text))
    return score


def _scored_windows(
    transcript: Transcript, target_seconds: float = 35.0
) -> list[tuple[float, float, float]]:
    """Every legal window with its score, best first.

    Windows are anchored to segment boundaries so results satisfy rung 4 by
    construction rather than by luck.
    """
    segments = transcript.segments
    scored: list[tuple[float, float, float]] = []

    for index, anchor in enumerate(segments):
        start = anchor.start
        collected: list[str] = []
        for follower in segments[index:]:
            if (follower.end - start) > MAX_CLIP_SECONDS:
                break
            collected.append(follower.text)
            end = follower.end
            if (end - start) >= MIN_CLIP_SECONDS:
                span = end - start
                # Prefer windows near the target length; a 15s and a 58s clip
                # are both legal but the middle of the range reads better.
                length_fit = 1.0 - min(abs(span - target_seconds) / target_seconds, 1.0)
                score = score_window(" ".join(collected), span) + 0.4 * length_fit
                scored.append((score, start, end))

    scored.sort(reverse=True)
    return scored


def heuristic_hooks(transcript: Transcript, count: int = 3) -> list[HookSelection]:
    """Top `count` non-overlapping windows, ranked.

    Overlap rejection is the point: the raw scan produces hundreds of windows
    that differ by one segment, so taking the top N by score alone would return
    five near-identical clips of the same moment.
    """
    if not transcript.segments:
        raise HookRejected("cannot run the heuristic on an empty transcript")
    if count < 1:
        raise ValueError("count must be at least 1")

    chosen: list[tuple[float, float, float]] = []
    for score, start, end in _scored_windows(transcript):
        if conflicts_with(start, end, [(s, e) for _, s, e in chosen]):
            continue
        chosen.append((score, start, end))
        if len(chosen) == count:
            break

    if not chosen:
        raise HookRejected(
            f"no window between {MIN_CLIP_SECONDS:.0f}s and {MAX_CLIP_SECONDS:.0f}s "
            "exists in this transcript"
        )

    return [
        HookSelection(
            start=start,
            end=end,
            score=round(score, 3),
            rank=rank,
            reason="Chosen by the deterministic heuristic after the model failed validation.",
            origin="heuristic",
        )
        for rank, (score, start, end) in enumerate(chosen, start=1)
    ]


def heuristic_hook(transcript: Transcript) -> HookSelection:
    """The single best window. Kept for the CLI's single-clip path."""
    return heuristic_hooks(transcript, count=1)[0]
