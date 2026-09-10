"""Caption Output Tokens, transcribed from design.md.

One source of truth lives in design.md; this module is its executable form.
`rules.md` forbids any hex, size or duration outside the token set, so the
renderer reads these names and never a literal.

If you change a value here, change design.md in the same commit. A stale
document is worse than a missing one.
"""

from __future__ import annotations

from typing import Final

# --- Geometry, authored for a 1080 x 1920 frame -----------------------------
FRAME_WIDTH: Final = 1080
FRAME_HEIGHT: Final = 1920
FRAME_RATE: Final = 30

FONT_FAMILY: Final = "Montserrat ExtraBold"
FONT_FAMILY_FALLBACK: Final = "DejaVu Sans Bold"
FONT_SIZE: Final = 84  # 4.4% of frame height
LINE_HEIGHT: Final = 1.15
UPPERCASE: Final = True
MAX_WORDS_PER_LINE: Final = 3
MAX_LINES: Final = 2
SAFE_AREA_BOTTOM: Final = 420  # clears platform UI overlays
SAFE_AREA_X: Final = 90

# --- Colour -----------------------------------------------------------------
# Legibility over arbitrary video comes from the stroke, not from a ratio
# against a known background: 19.80:1 inactive and 14.75:1 active against
# STROKE_COLOR. The stroke is structural and must not be reduced.
COLOR_INACTIVE: Final = "#FFFFFF"
COLOR_ACTIVE: Final = "#F2E14C"
STROKE_COLOR: Final = "#0A0A0A"
STROKE_WIDTH: Final = 8
SHADOW_DEPTH: Final = 4  # design.md: 0 4px 12px rgba(10,10,10,0.55)

# --- Motion, frame-quantised at 30 fps --------------------------------------
# Active vs inactive is only 1.34:1 in luminance, so colour cannot carry the
# signal alone. The pop scale is load-bearing, not decoration.
POP_DURATION_MS: Final = 100  # 3 frames
POP_SCALE_FROM: Final = 0.88
POP_SCALE_TO: Final = 1.06
SETTLE_DURATION_MS: Final = 67  # 2 frames, 1.06 back to 1.00
FADE_IN_MS: Final = 67  # 2 frames

# Line entrance: each new line fades up and rises slightly into place, so a
# line change reads as a beat rather than a jump-cut of text. Applied only to
# a line's first word event — retriggering it per word would make the caption
# jitter continuously.
ENTRANCE_FADE_MS: Final = 100  # 3 frames
ENTRANCE_RISE_PX: Final = 28   # travel distance, upward

# Depth. The stroke carries legibility; these carry the sense that the text
# sits on the frame rather than beside it.
GLOW_ALPHA: Final = 0x73  # shadow opacity, 0x00 opaque .. 0xFF clear
# caption.word-advance comes from Whisper word timings, never a fixed interval.


def assert_frame_aligned() -> None:
    """Fail loudly if a caption duration stops being a whole frame count.

    250ms is 7.5 frames and judders when baked into a fixed frame grid; this
    guard is here so that mistake cannot be reintroduced silently.
    """
    frame_ms = 1000 / FRAME_RATE
    for name, value in (
        ("POP_DURATION_MS", POP_DURATION_MS),
        ("SETTLE_DURATION_MS", SETTLE_DURATION_MS),
        ("FADE_IN_MS", FADE_IN_MS),
    ):
        frames = value / frame_ms
        if abs(frames - round(frames)) > 0.05:
            raise ValueError(
                f"{name} is {value}ms = {frames:.2f} frames at {FRAME_RATE}fps; "
                "caption durations must be whole frames"
            )
