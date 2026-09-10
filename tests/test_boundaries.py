"""Clip boundaries.

The defect these defend against, reported from real use: "it feels too short,
and the message about the video doesn't show up — it just cuts off in the
middle". Every clip was exactly one 25-second prompt chunk, because the merged
transcript's arbitrary walls were the only boundaries the model could name.
"""

from __future__ import annotations

from clipping.core.boundaries import (
    PREFERRED_MIN_SECONDS,
    ends_a_sentence,
    is_well_formed,
    snap_to_sentences,
)
from clipping.core.models import MAX_CLIP_SECONDS, Segment, Transcript


def build(*texts: str, seconds: float = 5.0) -> Transcript:
    segments = [
        Segment(text=text, start=index * seconds, end=(index + 1) * seconds)
        for index, text in enumerate(texts)
    ]
    return Transcript(segments=segments, source_duration=len(texts) * seconds)


SPEECH = build(
    "So here is the thing.",                    # 0-5     sentence
    "Most people believe you need willpower",   # 5-10    continues...
    "but that is completely wrong.",            # 10-15   ...ends here
    "I spent two years failing at this.",       # 15-20   sentence
    "And then one morning it clicked,",         # 20-25   continues...
    "I stopped negotiating with myself.",       # 25-30   ...ends here
    "That single change doubled my output.",    # 30-35   sentence
    "Anyway, back to the sponsor.",             # 35-40   sentence
)


def test_start_moves_back_to_the_beginning_of_its_sentence() -> None:
    """A clip opening on 'but that is completely wrong' has no subject."""
    start, _ = snap_to_sentences(11.0, 20.0, SPEECH)
    assert start == 5.0  # back to "Most people believe you need willpower"


def test_end_moves_forward_to_finish_its_sentence() -> None:
    _, end = snap_to_sentences(0.0, 22.0, SPEECH, preferred_min=0.0)
    assert end == 30.0  # forward to "...I stopped negotiating with myself."


def test_a_short_span_grows_until_the_point_can_land() -> None:
    """The reported defect: 24s of setup with no payoff."""
    start, end = snap_to_sentences(0.0, 5.0, SPEECH)
    assert end - start >= PREFERRED_MIN_SECONDS


def test_growth_stops_at_the_maximum() -> None:
    long_speech = build(*[f"Sentence number {i}." for i in range(40)], seconds=5.0)
    start, end = snap_to_sentences(0.0, 5.0, long_speech)
    assert end - start <= MAX_CLIP_SECONDS


def test_a_span_already_long_enough_is_left_alone() -> None:
    start, end = snap_to_sentences(0.0, 35.0, SPEECH)
    assert (start, end) == (0.0, 35.0)


def test_a_timestamp_in_a_gap_snaps_to_real_speech() -> None:
    gapped = Transcript(
        segments=[
            Segment(text="First thought here.", start=0.0, end=10.0),
            Segment(text="Second thought here.", start=100.0, end=140.0),
        ],
        source_duration=200.0,
    )
    start, _ = snap_to_sentences(55.0, 140.0, gapped)
    assert start == 100.0


def test_snapped_spans_stay_legal_clips() -> None:
    start, end = snap_to_sentences(11.0, 16.0, SPEECH)
    assert is_well_formed(start, end)


def test_an_empty_transcript_is_returned_unchanged() -> None:
    empty = Transcript(segments=[], source_duration=0.0)
    assert snap_to_sentences(10.0, 40.0, empty) == (10.0, 40.0)


def test_sentence_detection_reads_punctuation() -> None:
    assert ends_a_sentence("That is the point.")
    assert ends_a_sentence("Really?")
    assert not ends_a_sentence("and then he said")


UNPUNCTUATED = build(
    "jadi dimana pun juga",       # 0-5     no sentence end
    "nanti aku wachap kamu deh",  # 5-10
    "tapi memang bener-bener",    # 10-15
    "oh baru nanti kayaknya",     # 15-20
    "tiga lagi gore lagi",        # 20-25
    "iya di sepatahnya",          # 25-30
    "tiga baru kelemin",          # 30-35
    "kok acitnya melben enak",    # 35-40
)


def test_a_sparsely_punctuated_transcript_still_cuts_on_a_pause() -> None:
    """Whisper punctuates Indonesian sparsely — 14% of segments on a real
    episode. Without a pause fallback the clip clamps to an arbitrary
    timestamp and cuts mid-word, which is the original bug all over again."""
    start, end = snap_to_sentences(0.0, 5.0, UNPUNCTUATED)
    boundaries = {seg.end for seg in UNPUNCTUATED.segments} | {0.0}
    assert end in boundaries, f"{end} is not a speech boundary"


def test_the_pause_fallback_still_respects_the_maximum() -> None:
    long_unpunctuated = build(*[f"kata nomor {i}" for i in range(40)], seconds=5.0)
    start, end = snap_to_sentences(0.0, 5.0, long_unpunctuated)
    assert end - start <= MAX_CLIP_SECONDS
    assert end in {seg.end for seg in long_unpunctuated.segments}
