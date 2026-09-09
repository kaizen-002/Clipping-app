"""The validation ladder and the deterministic fallback."""

from __future__ import annotations

import pytest

from clipping.core.hooks import (
    HookRejected,
    heuristic_hook,
    heuristic_hooks,
    validate_candidate,
)
from clipping.core.models import HookCandidate, Segment, Transcript


def transcript(*spans: tuple[float, float, str], duration: float = 600.0) -> Transcript:
    return Transcript(
        segments=[Segment(start=s, end=e, text=t) for s, e, t in spans],
        source_duration=duration,
    )


def test_accepts_a_clean_candidate() -> None:
    source = transcript((100.0, 130.0, "a claim worth clipping"))
    outcome = validate_candidate(
        HookCandidate(start_seconds=100.0, end_seconds=130.0, reason="strong"), source
    )
    assert outcome.start == 100.0
    assert outcome.end == 130.0
    assert outcome.truncated is False


def test_rejects_a_span_past_the_episode_end() -> None:
    source = transcript((100.0, 130.0, "text"), duration=120.0)
    with pytest.raises(HookRejected, match="outside the episode"):
        validate_candidate(
            HookCandidate(start_seconds=100.0, end_seconds=200.0, reason="x"), source
        )


def test_rejects_a_backwards_span() -> None:
    source = transcript((0.0, 600.0, "text"))
    with pytest.raises(HookRejected, match="not before"):
        validate_candidate(
            HookCandidate(start_seconds=300.0, end_seconds=100.0, reason="x"), source
        )


def test_truncates_an_overlong_span_and_marks_it() -> None:
    source = transcript((0.0, 600.0, "text"))
    outcome = validate_candidate(
        HookCandidate(start_seconds=10.0, end_seconds=200.0, reason="x"), source
    )
    assert outcome.end == 70.0
    assert outcome.truncated is True


def test_rejects_a_span_under_the_minimum() -> None:
    source = transcript((0.0, 600.0, "text"))
    with pytest.raises(HookRejected, match="shorter than"):
        validate_candidate(
            HookCandidate(start_seconds=10.0, end_seconds=18.0, reason="x"), source
        )


def test_rejects_timestamps_that_land_in_a_gap() -> None:
    """A timestamp between segments was not read off the transcript."""
    source = transcript((0.0, 50.0, "first"), (400.0, 500.0, "second"))
    with pytest.raises(HookRejected, match="falls in a gap"):
        validate_candidate(
            HookCandidate(start_seconds=200.0, end_seconds=430.0, reason="x"), source
        )


def test_heuristic_prefers_denser_more_hooklike_speech() -> None:
    source = transcript(
        (0.0, 30.0, "um so yeah anyway"),
        (30.0, 60.0, "here's the thing nobody tells you about this and it changed everything"),
        (60.0, 90.0, "right"),
    )
    selection = heuristic_hook(source)
    assert selection.origin == "heuristic"
    assert 15.0 <= selection.duration <= 60.0


def test_heuristic_refuses_a_transcript_with_no_legal_window() -> None:
    source = transcript((0.0, 5.0, "too short"), duration=5.0)
    with pytest.raises(HookRejected, match="no window"):
        heuristic_hook(source)


def test_heuristic_refuses_an_empty_transcript() -> None:
    with pytest.raises(HookRejected, match="empty transcript"):
        heuristic_hook(Transcript(segments=[], source_duration=0.0))


def test_heuristic_returns_ranked_non_overlapping_windows() -> None:
    """Without overlap rejection this returns N near-identical clips."""
    spans = []
    for i in range(12):
        start = i * 20.0
        spans.append((start, start + 20.0, f"here's the thing nobody tells you point {i} " * 3))
    source = transcript(*spans, duration=240.0)

    selections = heuristic_hooks(source, count=3)
    assert len(selections) == 3
    assert [s.rank for s in selections] == [1, 2, 3]
    assert [s.score for s in selections] == sorted((s.score for s in selections), reverse=True)

    for earlier, later in zip(selections, selections[1:]):
        overlapping = earlier.start < later.end and earlier.end > later.start
        assert not overlapping, f"{earlier.start}-{earlier.end} overlaps {later.start}-{later.end}"


def test_heuristic_returns_fewer_when_the_episode_is_short() -> None:
    """Three clips cannot be found in an episode with room for one."""
    source = transcript((0.0, 20.0, "one window only here"), duration=20.0)
    assert len(heuristic_hooks(source, count=3)) == 1
