"""Caption line grouping, ASS generation, and the SRT sidecar.

ASS is the animation source. SRT is a line-level sidecar for platform upload
only and can never express per-word timing or styling — that incompatibility is
what made two of the original acceptance criteria mutually impossible.
"""

from __future__ import annotations

from clipping.core import caption_tokens as tokens
from clipping.core.models import CaptionLine, Word


def group_into_lines(
    words: list[Word], max_words: int = tokens.MAX_WORDS_PER_LINE
) -> list[CaptionLine]:
    """Chunk words into on-screen lines.

    A gap longer than 0.6 s reads as a new thought, so it breaks the line even
    when the current one is not full. Without this, a line can span a pause and
    sit on screen looking stale.
    """
    if max_words < 1:
        raise ValueError("max_words must be at least 1")

    lines: list[CaptionLine] = []
    current: list[Word] = []

    for word in words:
        if current:
            gap = word.start - current[-1].end
            if len(current) >= max_words or gap > 0.6:
                lines.append(CaptionLine(words=current))
                current = []
        current.append(word)

    if current:
        lines.append(CaptionLine(words=current))
    return lines


def _ass_colour(hex_colour: str, alpha: int = 0) -> str:
    """Convert #RRGGBB to ASS &HAABBGGRR. ASS reverses the byte order."""
    value = hex_colour.lstrip("#")
    if len(value) != 6:
        raise ValueError(f"expected #RRGGBB, got {hex_colour!r}")
    red, green, blue = value[0:2], value[2:4], value[4:6]
    return f"&H{alpha:02X}{blue}{green}{red}".upper()


def _ass_timestamp(seconds: float) -> str:
    """ASS wants H:MM:SS.cc — centiseconds, and a single-digit hour."""
    if seconds < 0:
        seconds = 0.0
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    centis = int(round((secs - int(secs)) * 100))
    secs = int(secs)
    if centis == 100:  # rounding carried into the next second
        centis = 0
        secs += 1
    return f"{int(hours)}:{int(minutes):02d}:{secs:02d}.{centis:02d}"


def _escape(text: str) -> str:
    """Neutralise ASS markup in transcript text.

    A brace opens an override block in ASS, so an unescaped one from the
    transcript would be swallowed as styling instead of shown as a character.
    """
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def build_ass(words: list[Word], clip_start: float) -> str:
    """Render an ASS file: one Dialogue event per word.

    Each event shows the whole line, with the currently-spoken word in the
    active colour and carrying the pop transform. Word advance comes from the
    Whisper timings, never a fixed interval.

    `clip_start` rebases absolute episode time to clip-relative time. This is
    the single place the rebase happens.
    """
    tokens.assert_frame_aligned()

    lines = group_into_lines(words)
    events: list[str] = []

    for line in lines:
        for active_index, active_word in enumerate(line.words):
            start = max(active_word.start - clip_start, 0.0)

            # Hold the line until the next word takes over, rather than ending
            # when this word stops being spoken. Whisper leaves small gaps
            # between words, and an event that ends at word.end makes the whole
            # line blink out during every one of them.
            is_last = active_index == len(line.words) - 1
            next_boundary = (
                line.words[active_index + 1].start if not is_last else active_word.end
            )
            end = max(next_boundary - clip_start, 0.0)
            if end <= start:
                continue  # a zero-length word would emit an event nothing can see

            rendered: list[str] = []
            for index, word in enumerate(line.words):
                text = _escape(word.text.upper() if tokens.UPPERCASE else word.text)
                if index == active_index:
                    rendered.append(_active_span(text))
                else:
                    rendered.append(text)

            body = " ".join(rendered)

            # Only the line's first event carries the entrance. Retriggering
            # it on every word would make the caption jitter continuously
            # instead of settling.
            prefix = _entrance() if active_index == 0 else ""

            events.append(
                f"Dialogue: 0,{_ass_timestamp(start)},{_ass_timestamp(end)},"
                f"Caption,,0,0,0,,{prefix}{body}"
            )

    return _ass_header() + "\n".join(events) + "\n"


def _entrance() -> str:
    r"""Fade up and rise into place at the start of a line.

    ``\move`` needs absolute coordinates, so the anchor is derived from the
    same tokens the style header uses — bottom-centre, inset by the bottom
    safe area. Deriving it keeps one source of truth; hard-coding it would put
    the safe-area margin in two places that could drift apart.
    """
    fade = tokens.ENTRANCE_FADE_MS
    rise = tokens.ENTRANCE_RISE_PX
    anchor_x = tokens.FRAME_WIDTH // 2
    anchor_y = tokens.FRAME_HEIGHT - tokens.SAFE_AREA_BOTTOM
    return (
        f"{{\\fad({fade},0)"
        f"\\move({anchor_x},{anchor_y + rise},{anchor_x},{anchor_y},0,{fade})}}"
    )


def _active_span(text: str) -> str:
    """The active word: colour change plus the two-stage pop.

    Signalled twice on purpose — active vs inactive is only 1.34:1 in
    luminance, so colour alone would not read for a viewer with a colour vision
    deficiency, and would vanish on a yellow-ish frame.
    """
    active = _ass_colour(tokens.COLOR_ACTIVE)
    inactive = _ass_colour(tokens.COLOR_INACTIVE)
    pop_from = int(tokens.POP_SCALE_FROM * 100)
    pop_to = int(tokens.POP_SCALE_TO * 100)
    pop_ms = tokens.POP_DURATION_MS
    settle_end = pop_ms + tokens.SETTLE_DURATION_MS

    return (
        f"{{\\c{active}"
        f"\\fscx{pop_from}\\fscy{pop_from}"
        f"\\t(0,{pop_ms},\\fscx{pop_to}\\fscy{pop_to})"
        f"\\t({pop_ms},{settle_end},\\fscx100\\fscy100)}}"
        f"{text}"
        f"{{\\r\\c{inactive}}}"
    )


def _ass_header() -> str:
    """Script and style headers built entirely from the caption tokens."""
    primary = _ass_colour(tokens.COLOR_INACTIVE)
    outline = _ass_colour(tokens.STROKE_COLOR)
    shadow = _ass_colour(tokens.STROKE_COLOR, alpha=0x73)  # 0.55 alpha -> 45% opaque

    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {tokens.FRAME_WIDTH}
PlayResY: {tokens.FRAME_HEIGHT}
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, \
BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, \
BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{tokens.FONT_FAMILY},{tokens.FONT_SIZE},{primary},{primary},\
{outline},{shadow},-1,0,0,0,100,100,0,0,1,{tokens.STROKE_WIDTH},\
{tokens.SHADOW_DEPTH},2,{tokens.SAFE_AREA_X},{tokens.SAFE_AREA_X},\
{tokens.SAFE_AREA_BOTTOM},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def build_srt(words: list[Word], clip_start: float) -> str:
    """Line-level SRT sidecar for platform upload.

    Deliberately not the animation source. SRT has no per-word timing and no
    styling; describing it as the caption source is what made the original
    acceptance criteria contradictory.
    """
    lines = group_into_lines(words)
    blocks: list[str] = []

    for index, line in enumerate(lines, start=1):
        start = max(line.start - clip_start, 0.0)
        end = max(line.end - clip_start, 0.0)
        blocks.append(
            f"{index}\n{_srt_timestamp(start)} --> {_srt_timestamp(end)}\n{line.text}\n"
        )

    return "\n".join(blocks)


def _srt_timestamp(seconds: float) -> str:
    """SRT wants HH:MM:SS,mmm with a comma before the milliseconds."""
    if seconds < 0:
        seconds = 0.0
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    millis = int(round((secs - int(secs)) * 1000))
    secs = int(secs)
    if millis == 1000:
        millis = 0
        secs += 1
    return f"{int(hours):02d}:{int(minutes):02d}:{secs:02d},{millis:03d}"
