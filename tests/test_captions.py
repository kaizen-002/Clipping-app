"""Caption grouping and the ASS/SRT output."""

from __future__ import annotations

import pytest

from clipping.core import caption_tokens as tokens
from clipping.core.captions import (
    _ass_colour,
    _ass_timestamp,
    build_ass,
    build_srt,
    group_into_lines,
)
from clipping.core.models import Word


def words(*items: tuple[str, float, float]) -> list[Word]:
    return [Word(text=t, start=s, end=e) for t, s, e in items]


def test_lines_hold_at_most_the_token_word_count() -> None:
    sample = words(*[(f"w{i}", i * 0.3, i * 0.3 + 0.3) for i in range(9)])
    lines = group_into_lines(sample)
    assert all(len(line.words) <= tokens.MAX_WORDS_PER_LINE for line in lines)


def test_a_long_pause_breaks_the_line_early() -> None:
    sample = words(("a", 0.0, 0.2), ("b", 3.0, 3.2))
    lines = group_into_lines(sample)
    assert len(lines) == 2


def test_ass_emits_one_event_per_word() -> None:
    """MVP acceptance 6: one timed event per word."""
    sample = words(("one", 10.0, 10.4), ("two", 10.4, 10.9), ("three", 10.9, 11.5))
    output = build_ass(sample, clip_start=10.0)
    assert output.count("Dialogue:") == 3


def test_ass_times_are_clip_relative() -> None:
    sample = words(("word", 100.0, 100.5))
    output = build_ass(sample, clip_start=100.0)
    assert "0:00:00.00,0:00:00.50" in output


def test_active_word_is_signalled_by_colour_and_scale() -> None:
    """Colour alone is only 1.34:1 in luminance, so the pop is load-bearing."""
    sample = words(("one", 0.0, 0.4), ("two", 0.4, 0.8))
    output = build_ass(sample, clip_start=0.0)
    assert _ass_colour(tokens.COLOR_ACTIVE) in output
    assert "\\fscx" in output and "\\t(" in output


def test_ass_header_carries_the_stroke_and_safe_area() -> None:
    output = build_ass(words(("a", 0.0, 0.5)), clip_start=0.0)
    assert f"PlayResY: {tokens.FRAME_HEIGHT}" in output
    assert f",{tokens.STROKE_WIDTH}," in output
    assert f",{tokens.SAFE_AREA_BOTTOM}," in output


def test_braces_in_transcript_text_cannot_open_an_override_block() -> None:
    output = build_ass(words(("{drop}", 0.0, 0.5)), clip_start=0.0)
    assert "\\{DROP\\}" in output  # uppercased per caption.case


def test_colour_conversion_reverses_the_byte_order() -> None:
    assert _ass_colour("#F2E14C") == "&H004CE1F2"


def test_timestamp_rounding_carries_into_the_next_second() -> None:
    assert _ass_timestamp(1.999) == "0:00:02.00"


def test_srt_is_line_level_not_word_level() -> None:
    sample = words(("one", 0.0, 0.4), ("two", 0.4, 0.8), ("three", 0.8, 1.2))
    output = build_srt(sample, clip_start=0.0)
    assert output.count("-->") == 1
    assert "one two three" in output


def test_caption_durations_are_whole_frames() -> None:
    """250ms would be 7.5 frames at 30fps and judder when baked in."""
    tokens.assert_frame_aligned()


def test_zero_length_words_emit_no_event() -> None:
    output = build_ass(words(("ghost", 5.0, 5.0)), clip_start=5.0)
    assert "Dialogue:" not in output


def test_line_stays_on_screen_through_inter_word_gaps() -> None:
    """Whisper leaves gaps between words; the line must not blink out in them.

    Regression: events originally ended at each word's own end time, so a
    50ms gap produced a frame with no caption at all.
    """
    sample = words(("one", 0.0, 0.40), ("two", 0.45, 0.85), ("three", 0.90, 1.30))
    output = build_ass(sample, clip_start=0.0)

    events = [line for line in output.splitlines() if line.startswith("Dialogue:")]
    spans = [line.split(",")[1:3] for line in events]
    # Each event must begin exactly where the previous one ended: no holes.
    for (_, previous_end), (next_start, _) in zip(spans, spans[1:]):
        assert previous_end == next_start


def test_only_the_first_word_of_a_line_carries_the_entrance() -> None:
    """Retriggering the entrance per word makes the caption jitter instead of
    settling, which reads as a glitch rather than a beat."""
    sample = words(("one", 0.0, 0.40), ("two", 0.45, 0.85), ("three", 0.90, 1.30))
    events = [l for l in build_ass(sample, 0.0).splitlines() if l.startswith("Dialogue:")]
    assert events[0].count(r"\fad") == 1
    assert all(r"\fad" not in event for event in events[1:])


def test_the_entrance_rises_to_the_style_safe_area() -> None:
    """The move target must match the margin in the style header, or the line
    animates to one place and then jumps to another."""
    output = build_ass(words(("hello", 0.0, 0.5)), 0.0)
    anchor_y = tokens.FRAME_HEIGHT - tokens.SAFE_AREA_BOTTOM
    assert f",{anchor_y},0," in output or f",{anchor_y}," in output
