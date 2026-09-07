"""Editor invariants, enforced in the domain layer.

PRD.md flags the timing invariant as the one most likely to be broken by a naive
implementation, "because the caption text and the timing array look independent
and are not". They are not independent: the timings were measured from audio and
cannot be regenerated from edited text.
"""

from __future__ import annotations

from clipping.core.models import (
    MAX_CLIP_SECONDS,
    MIN_CLIP_SECONDS,
    Clip,
    Word,
)


class EditRejected(Exception):
    """An edit would violate an invariant. The message says which one."""


def retime_words(existing: list[Word], edited_text: list[str]) -> list[Word]:
    """Reconcile edited caption text with measured word timings.

    The three cases PRD.md specifies:

    - same word count  -> remap timings positionally
    - a word deleted   -> its timing is dropped
    - a word inserted  -> it splits its neighbour's interval evenly

    Anything that would leave a word with no timing is rejected rather than
    guessed at. A guessed timing desynchronises the caption from the audio,
    which is the one thing this product exists to get right.
    """
    if not edited_text:
        raise EditRejected("a caption line cannot be empty")
    if any(not token.strip() for token in edited_text):
        raise EditRejected("a caption line cannot contain an empty word")

    if not existing:
        raise EditRejected("cannot time new words against an empty timing array")

    if len(edited_text) == len(existing):
        return [
            Word(text=token, start=word.start, end=word.end)
            for token, word in zip(edited_text, existing)
        ]

    if len(edited_text) < len(existing):
        return _apply_deletions(existing, edited_text)

    return _apply_insertions(existing, edited_text)


def _apply_deletions(existing: list[Word], edited_text: list[str]) -> list[Word]:
    """Match the shorter edited text back onto the original words in order.

    A greedy in-order match: every remaining word keeps the timing of the
    original it corresponds to. If the edited text is not a subsequence of the
    original, we cannot say which timing belongs to which word, so we refuse.
    """
    result: list[Word] = []
    cursor = 0
    for token in edited_text:
        match = None
        while cursor < len(existing):
            candidate = existing[cursor]
            cursor += 1
            if _same_word(candidate.text, token):
                match = candidate
                break
        if match is None:
            raise EditRejected(
                f"cannot place {token!r}: deleting words is supported, but rewriting "
                "them changes which timing belongs to which word. Edit one word at a "
                "time, or keep the word count the same."
            )
        result.append(Word(text=token, start=match.start, end=match.end))
    return result


def _apply_insertions(existing: list[Word], edited_text: list[str]) -> list[Word]:
    """Insert new words by splitting the interval of the word they follow."""
    result: list[Word] = []
    cursor = 0
    pending: list[str] = []

    for token in edited_text:
        if cursor < len(existing) and _same_word(existing[cursor].text, token):
            anchor = existing[cursor]
            cursor += 1
            if pending:
                result.extend(_split_interval(anchor, pending, token))
                pending = []
            else:
                result.append(Word(text=token, start=anchor.start, end=anchor.end))
        else:
            pending.append(token)

    if pending:
        # Trailing insertions split the final original word.
        if not result:
            raise EditRejected(
                "cannot time inserted words with no surrounding word to split"
            )
        tail = result.pop()
        result.extend(_split_interval(tail, [], tail.text, extra_after=pending))

    return result


def _split_interval(
    anchor: Word,
    before: list[str],
    anchor_text: str,
    extra_after: list[str] | None = None,
) -> list[Word]:
    """Divide `anchor`'s interval evenly among the inserted words and itself."""
    after = extra_after or []
    tokens = [*before, anchor_text, *after]
    slice_length = anchor.duration / len(tokens)
    if slice_length <= 0:
        raise EditRejected(
            f"cannot insert words into {anchor.text!r}: it has no measurable duration"
        )
    return [
        Word(
            text=token,
            start=anchor.start + index * slice_length,
            end=anchor.start + (index + 1) * slice_length,
        )
        for index, token in enumerate(tokens)
    ]


def _same_word(left: str, right: str) -> bool:
    """Compare words ignoring case and surrounding punctuation.

    Fixing a word's capitalisation or stripping a stray comma is a formatting
    edit, not a different word, and should not cost the user their timings.
    """
    return _normalise(left) == _normalise(right)


def _normalise(token: str) -> str:
    return token.strip().strip(".,!?;:\"'—-").casefold()


def adjust_bounds(clip: Clip, start: float, end: float) -> Clip:
    """Move the clip's start/end, dropping words that fall outside.

    Words are dropped, never rescaled. Rescaling would slide every remaining
    word off the audio it was measured against.
    """
    if end <= start:
        raise EditRejected(f"end ({end:.2f}s) must be after start ({start:.2f}s)")

    span = end - start
    if span < MIN_CLIP_SECONDS:
        raise EditRejected(
            f"clip is {span:.1f}s; the minimum is {MIN_CLIP_SECONDS:.0f}s"
        )
    if span > MAX_CLIP_SECONDS:
        raise EditRejected(
            f"clip is {span:.1f}s; the maximum is {MAX_CLIP_SECONDS:.0f}s"
        )

    kept = [word for word in clip.words if word.start >= start and word.end <= end]
    if not kept:
        raise EditRejected(
            "those bounds contain no complete words — the clip would have no captions"
        )

    return clip.model_copy(update={"start": start, "end": end, "words": kept})
