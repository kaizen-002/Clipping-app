"""The invariant PRD.md flags as most likely to be broken.

Caption text and the timing array look independent and are not: the timings
were measured from audio and cannot be regenerated from edited text.
"""

from __future__ import annotations

import pytest

from clipping.core.editing import EditRejected, adjust_bounds, retime_words
from clipping.core.models import Clip, Word


def words(*items: tuple[str, float, float]) -> list[Word]:
    return [Word(text=t, start=s, end=e) for t, s, e in items]


def test_same_word_count_remaps_timings_positionally() -> None:
    original = words(("hello", 0.0, 0.5), ("world", 0.5, 1.0))
    result = retime_words(original, ["Hello", "everyone"])
    assert [w.text for w in result] == ["Hello", "everyone"]
    assert result[1].start == 0.5
    assert result[1].end == 1.0


def test_deleting_a_word_drops_its_timing_and_keeps_the_rest() -> None:
    original = words(("the", 0.0, 0.2), ("big", 0.2, 0.6), ("dog", 0.6, 1.0))
    result = retime_words(original, ["the", "dog"])
    assert [w.text for w in result] == ["the", "dog"]
    assert result[1].start == 0.6  # "dog" keeps the timing measured for "dog"


def test_inserting_a_word_splits_its_neighbours_interval() -> None:
    original = words(("the", 0.0, 0.4), ("dog", 0.4, 1.0))
    result = retime_words(original, ["the", "big", "dog"])
    assert [w.text for w in result] == ["the", "big", "dog"]
    # "big" and "dog" share the interval that used to belong to "dog" alone.
    assert result[1].start == pytest.approx(0.4)
    assert result[2].end == pytest.approx(1.0)
    assert result[1].end == pytest.approx(result[2].start)


def test_rewriting_a_word_is_rejected_rather_than_guessed() -> None:
    """The failure mode that matters: a guessed timing desyncs the caption."""
    original = words(("the", 0.0, 0.2), ("big", 0.2, 0.6), ("dog", 0.6, 1.0))
    with pytest.raises(EditRejected, match="cannot place"):
        retime_words(original, ["the", "enormous"])


def test_empty_line_is_rejected() -> None:
    original = words(("word", 0.0, 0.5))
    with pytest.raises(EditRejected, match="cannot be empty"):
        retime_words(original, [])


def test_punctuation_and_case_changes_keep_their_timings() -> None:
    """Fixing capitalisation is a formatting edit, not a different word."""
    original = words(("hello,", 0.0, 0.5), ("world", 0.5, 1.0))
    result = retime_words(original, ["Hello", "world!"])
    assert result[0].start == 0.0
    assert result[1].end == 1.0


def clip_with(*items: tuple[str, float, float]) -> Clip:
    return Clip(
        source_url="https://example.invalid/watch?v=x",
        start=10.0,
        end=50.0,
        words=words(*items),
        origin="llm",
        reason="test",
    )


def test_adjusting_bounds_drops_outside_words_without_rescaling() -> None:
    clip = clip_with(("a", 10.0, 11.0), ("b", 30.0, 31.0), ("c", 48.0, 49.0))
    adjusted = adjust_bounds(clip, 20.0, 40.0)
    assert [w.text for w in adjusted.words] == ["b"]
    assert adjusted.words[0].start == 30.0  # unchanged, not rescaled


def test_bounds_must_respect_the_clip_length_rule() -> None:
    clip = clip_with(("a", 10.0, 11.0), ("b", 20.0, 21.0))
    with pytest.raises(EditRejected, match="minimum is 15s"):
        adjust_bounds(clip, 10.0, 20.0)
    with pytest.raises(EditRejected, match="maximum is 60s"):
        adjust_bounds(clip, 10.0, 100.0)


def test_end_before_start_is_rejected() -> None:
    clip = clip_with(("a", 10.0, 11.0))
    with pytest.raises(EditRejected, match="must be after"):
        adjust_bounds(clip, 40.0, 20.0)


def test_bounds_containing_no_words_are_rejected() -> None:
    clip = clip_with(("a", 10.0, 11.0))
    with pytest.raises(EditRejected, match="no complete words"):
        adjust_bounds(clip, 20.0, 40.0)
