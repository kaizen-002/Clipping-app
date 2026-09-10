"""Snapping clip boundaries to where thoughts actually start and end.

A clip that begins mid-phrase reads as broken however good the moment inside it
is. The model proposes an approximate span; this moves it to sentence edges and
gives it room to land a point.

Pure functions over values, so the behaviour that decides whether a clip feels
finished is testable without a model or a network.
"""

from __future__ import annotations

from clipping.core.models import MAX_CLIP_SECONDS, MIN_CLIP_SECONDS, Transcript

# A hook needs setup and payoff. 24 seconds is usually only the setup, which is
# what "it just cuts off in the middle" means in practice.
PREFERRED_MIN_SECONDS = 32.0

_SENTENCE_END = (".", "!", "?", "…")


def ends_a_sentence(text: str) -> bool:
    """True when this segment's text closes a sentence.

    Whisper punctuates its output, so the transcript already carries the
    information; nothing here needs to infer it from timing.
    """
    return text.rstrip().endswith(_SENTENCE_END)


def snap_to_sentences(
    start: float,
    end: float,
    transcript: Transcript,
    preferred_min: float = PREFERRED_MIN_SECONDS,
) -> tuple[float, float]:
    """Move an approximate span onto sentence boundaries and give it room.

    Three moves, in order:

    1. Pull `start` back to the beginning of the sentence it lands inside, so
       the clip does not open mid-phrase.
    2. Push `end` forward to the end of the sentence it lands inside, so the
       clip does not stop mid-phrase.
    3. Keep extending forward, one sentence at a time, until the clip is at
       least `preferred_min` — a point needs room to arrive.

    Every move is bounded by `MAX_CLIP_SECONDS`; a clip that cannot grow stays
    where it is rather than being stretched past the limit.
    """
    segments = transcript.segments
    if not segments:
        return start, end

    snapped_start = _sentence_start_at_or_before(start, segments)
    snapped_end = _sentence_end_at_or_after(end, segments)

    if snapped_end - snapped_start > MAX_CLIP_SECONDS:
        # Snapping overshot the limit. Prefer keeping the opening intact and
        # pulling the end back, because a clean start matters more than a
        # clean finish for something that has to survive three seconds of
        # scrolling.
        snapped_end = _last_pause_within(snapped_start, MAX_CLIP_SECONDS, segments)

    snapped_end = _grow_to_preferred(
        snapped_start, snapped_end, segments, preferred_min
    )
    return snapped_start, snapped_end


def _sentence_start_at_or_before(instant: float, segments) -> float:
    """The start of the sentence containing `instant`."""
    index = _index_containing(instant, segments)
    if index is None:
        return instant

    # Walk back while the previous segment does not close a sentence: those
    # segments are continuations of the same thought.
    while index > 0 and not ends_a_sentence(segments[index - 1].text):
        index -= 1
    return segments[index].start


def _sentence_end_at_or_after(instant: float, segments) -> float:
    """The end of the sentence containing `instant`."""
    index = _index_containing(instant, segments)
    if index is None:
        return instant

    while index < len(segments) - 1 and not ends_a_sentence(segments[index].text):
        index += 1
    return segments[index].end


def _last_pause_within(start: float, limit: float, segments) -> float:
    """The latest segment end within `limit`, preferring a sentence end.

    When no sentence end fits — Whisper punctuates some languages sparsely,
    and only 14% of segments end a sentence on an Indonesian transcript — a
    segment boundary is still a real pause in the speech, because segments come
    from voice activity detection. Cutting there beats cutting at an arbitrary
    timestamp, which lands mid-word.
    """
    ceiling = start + limit
    best_pause = start
    best_sentence = None

    for segment in segments:
        if segment.end <= start or segment.end > ceiling:
            continue
        best_pause = segment.end
        if ends_a_sentence(segment.text):
            best_sentence = segment.end

    return best_sentence if best_sentence is not None else (best_pause or ceiling)


def _grow_to_preferred(start: float, end: float, segments, preferred_min: float) -> float:
    """Extend forward a sentence at a time until the clip has room to land."""
    if end - start >= preferred_min:
        return end

    # Prefer growing to a sentence end. On a sparsely punctuated transcript
    # there may not be one in range, so a speech pause is the fallback.
    fallback = end
    for segment in segments:
        if segment.end <= end:
            continue
        if segment.end - start > MAX_CLIP_SECONDS:
            break
        fallback = segment.end
        if not ends_a_sentence(segment.text):
            continue
        end = segment.end
        if end - start >= preferred_min:
            return end

    return end if end - start >= preferred_min else fallback


def _index_containing(instant: float, segments) -> int | None:
    """Index of the segment holding `instant`, or the nearest one to it."""
    for index, segment in enumerate(segments):
        if segment.start <= instant <= segment.end:
            return index
        if segment.start > instant:
            # Landed in a gap: the following segment is the nearest speech.
            return index
    return len(segments) - 1 if segments else None


def is_well_formed(start: float, end: float) -> bool:
    """True when a snapped span is still a legal clip."""
    return MIN_CLIP_SECONDS <= (end - start) <= MAX_CLIP_SECONDS
