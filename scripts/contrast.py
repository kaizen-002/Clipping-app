"""Contrast checker for the product palette.

Every ratio the UI relies on comes from this script. Numbers typed into a
document rather than computed are wrong often enough to be worthless — the
first version of design.md had eight ratios in one table and every one was wrong,
including the four it marked "Pass". design.md has since been superseded by a
single dark product palette, but this check outlived it deliberately.

Run after changing any colour. Exits non-zero if any required pair fails.

    python scripts/contrast.py
"""

import sys

# The product commits to one dark surface, in the manner of the tools it sits
# beside. There is no light variant to keep in sync, and therefore no second
# palette to get wrong.
DARK = {
    "ground": "#0B0E14",
    "surface": "#141924",
    "raised": "#1B2230",
    "ink": "#EDF1F8",
    "muted-ink": "#8592AB",
    "disabled-ink": "#5F6B7E",
    "accent": "#6D4AFF",        # fill only
    "accent-hover": "#5B38F0",
    "accent-active": "#4E2CD9",
    "accent-strong": "#C4B8FF",  # text, links, focus ring
    "on-accent": "#FFFFFF",
    "hairline": "#232B3A",
    "success": "#4ADE80",
    "warning": "#FBBF24",
    "danger": "#FF7B72",
    "on-danger": "#0B0E14",
}

CAPTION = {
    "inactive": "#FFFFFF",
    "active": "#F2E14C",
    "stroke": "#0A0A0A",
}

AA_TEXT = 4.5
AA_NON_TEXT = 3.0


def luminance(hex_colour):
    h = hex_colour.lstrip("#")
    channels = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def ratio(a, b):
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def check(label, fg, bg, need, failures):
    r = ratio(fg, bg)
    ok = r >= need
    if not ok:
        failures.append("{}: {:.2f} < {}".format(label, r, need))
    print("  {} {:<44} {:6.2f}  (need {})".format("ok  " if ok else "FAIL", label, r, need))


def audit(name, p, failures):
    print("\n=== {} ===".format(name))
    g, s = p["ground"], p["surface"]

    print("  ---- panel separation: surface vs ground = {:.2f} ----".format(ratio(s, g)))
    print("  ---- raised vs ground = {:.2f} ----".format(ratio(p["raised"], g)))

    for token in ("ink", "muted-ink", "success", "warning", "danger"):
        check("{} on ground".format(token), p[token], g, AA_TEXT, failures)
        check("{} on surface".format(token), p[token], s, AA_TEXT, failures)

    # Accent fills are never text. What must pass is the text sitting on them.
    text_on_fill = p["on-accent"]
    for fill in ("accent", "accent-hover", "accent-active"):
        check("text on {} fill".format(fill), text_on_fill, p[fill], AA_TEXT, failures)

    check("focus ring (accent-strong) on ground", p["accent-strong"], g, AA_NON_TEXT, failures)
    check("focus ring (accent-strong) on surface", p["accent-strong"], s, AA_NON_TEXT, failures)
    check("on-danger text on danger fill", p["on-danger"], p["danger"], AA_TEXT, failures)

    # Secondary text, disabled text and the interactive accent must not collapse
    # into one another — that was a real defect in the first dark palette, where
    # all three were the same hex.
    for a, b in (("muted-ink", "accent"), ("muted-ink", "disabled-ink")):
        r = ratio(p[a], p[b])
        ok = r >= 1.5
        if not ok:
            failures.append("{} vs {} indistinguishable: {:.2f}".format(a, b, r))
        print("  {} {} vs {} distinguishable{:<10} {:6.2f}  (need 1.5)".format(
            "ok  " if ok else "FAIL", a, b, "", r))

    # Disabled text is exempt from AA (WCAG 1.4.3): reported, never enforced.
    print("  note disabled-ink on ground{:<22} {:6.2f}  (exempt)".format("", ratio(p["disabled-ink"], g)))


def audit_captions(failures):
    print("\n=== CAPTIONS (over arbitrary video) ===")
    print("  Legibility comes from the opaque stroke, not from a page background.")
    check("inactive word vs stroke", CAPTION["inactive"], CAPTION["stroke"], 7.0, failures)
    check("active word vs stroke", CAPTION["active"], CAPTION["stroke"], 7.0, failures)
    r = ratio(CAPTION["active"], CAPTION["inactive"])
    print("  note active vs inactive luminance{:<16} {:6.2f}".format("", r))
    print("       -> too close to carry the signal alone; the pop scale is required")


def audit_frames(fps=30):
    print("\n=== FRAME ALIGNMENT at {} fps ===".format(fps))
    frame_ms = 1000.0 / fps
    for label, ms in [
        ("caption.pop-duration", 100),
        ("caption.settle-duration", 67),
        ("caption.fade-in", 67),
        ("--duration-fast", 100),
        ("--duration-medium", 200),
        ("--duration-slow", 400),
    ]:
        frames = ms / frame_ms
        aligned = abs(frames - round(frames)) < 0.02
        print("  {} {:<28} {:>4} ms = {:5.2f} frames".format(
            "ok  " if aligned else "WARN", label, ms, frames))


def main():
    failures = []
    audit("PRODUCT (dark)", DARK, failures)
    audit_captions(failures)
    audit_frames()

    print()
    if failures:
        print("{} FAILURE(S):".format(len(failures)))
        for f in failures:
            print("  - {}".format(f))
        return 1
    print("All required pairs pass.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
