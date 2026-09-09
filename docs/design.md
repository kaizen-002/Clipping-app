# Design System — Local Podcast Shorts Generator

> **SUPERSEDED.** The UI palette in this document is no longer what the product
> uses. The app now commits to a single dark surface defined in
> `clipping/web/static/styles.css`, and there is no light variant.
>
> What survives, and is still binding:
> - **`scripts/contrast.py`** — still the gate. It verifies the current palette
>   and exits non-zero on a regression. It caught a failure in the replacement
>   palette too (`muted-ink` and `disabled-ink` at 1.45:1), which is the reason
>   it was kept rather than retired with the rest of this document.
> - **Caption Output Tokens** (below) — unchanged. Those are burned into the
>   exported video, not the page, and the renderer reads them from
>   `clipping/core/caption_tokens.py`.
> - **The accessibility floors** — 4.5:1 body text, 3:1 non-text and focus
>   rings, 44px targets, keyboard-operable timeline, no state signalled by
>   colour alone.
>
> Kept rather than deleted because a deleted document gets reconstructed from
> memory, and the reasoning below — particularly why the first contrast table
> was wrong — is worth more than the hexes it recommends.

This system covers **two surfaces**, and they follow different rules:

1. **The tool UI** — the local web app. Standard WCAG rules apply.
2. **The caption renderer** — the burned-in captions in the exported MP4. These
   sit on arbitrary video frames, so WCAG contrast ratios do not apply and
   legibility is guaranteed structurally instead. See **Caption Output Tokens**.

Every ratio in this document was computed with `scripts/contrast.py` (checked in),
not asserted. Re-run it after changing any colour.

## Brand Position

- Reads as a production tool, not a consumer app: no illustration, no mascot, no
  decorative gradient. Consequence — icons are functional line glyphs only.
- The video is the loudest thing on screen. Consequence — UI chrome stays low
  saturation, and the accent olive appears only on the primary action and the
  active timeline handle.
- Long-running work is normal here. Consequence — every stage shows elapsed and
  estimated time rather than an indeterminate spinner.

## Anti-Patterns

- Never script, handwritten or display-novelty fonts anywhere in the UI.
- Never pure-black shadows (`rgba(0,0,0,…)`); shadows are tinted with the ink hue.
- Never gradients on buttons or panels.
- Never text over a video frame in the UI without a solid backing surface.
- Never animated GIF loaders; CSS or SVG only.
- Never body copy below 1.4 line-height.
- Never an indeterminate spinner for a stage with a known duration estimate.
- Never colour as the only signal — pair it with text, an icon, or a shape change.
- Never reuse the **UI motion tokens** for caption animation, or the **caption
  tokens** for UI. They are different scales for different media.

## Colour — Light

```css
:root {
  --color-ground:        #F4F6FA; /* page */
  --color-surface:       #FFFFFF; /* panels, cards, inputs */
  --color-ink:           #16294B; /* primary text */
  --color-muted-ink:     #4A5B78; /* secondary text, placeholders */
  --color-disabled-ink:  #7C89A0; /* disabled text only, never body copy */
  --color-accent:        #A0AA54; /* FILL ONLY — never text on ground */
  --color-accent-hover:  #949E4E; /* fill, hover */
  --color-accent-active: #8F9A4B; /* fill, pressed */
  --color-accent-strong: #55611A; /* text, links, focus ring */
  --color-hairline:      #D8DFEA; /* 1px borders */
  --color-success:       #0F6B31;
  --color-warning:       #9A4B00;
  --color-danger:        #B0201F;
  --color-on-danger:     #FFFFFF; /* text on a danger fill */
}
```

| Token | Hex | Use | On ground | On surface | Verdict |
|---|---|---|---|---|---|
| `--color-surface` | `#FFFFFF` | Panels | 1.08 : 1 | — | Separation only; panels also carry a hairline |
| `--color-ink` | `#16294B` | Body text, headings | 13.36 : 1 | 14.45 : 1 | Pass AA and AAA |
| `--color-muted-ink` | `#4A5B78` | Secondary text | 6.35 : 1 | 6.87 : 1 | Pass AA |
| `--color-disabled-ink` | `#7C89A0` | Disabled labels | 3.06 : 1 | 3.31 : 1 | Below AA by intent — disabled text is exempt (WCAG 1.4.3), and it must never carry information available nowhere else |
| `--color-accent` | `#A0AA54` | Button and handle **fill** | 2.40 : 1 | 2.60 : 1 | **Fails as text.** Fill only, and only ever with `--color-ink` on top |
| `--color-accent-hover` | `#949E4E` | Button fill, hover | 2.67 : 1 | 2.89 : 1 | Fill only; `--color-ink` on it is 5.00 : 1 |
| `--color-accent-active` | `#8F9A4B` | Button fill, pressed | 2.82 : 1 | 3.05 : 1 | Fill only; `--color-ink` on it is 4.74 : 1 |
| `--color-accent-strong` | `#55611A` | Accent text, links, focus ring | 6.24 : 1 | 6.75 : 1 | Pass AA; also clears the 3:1 non-text bar |
| `--color-hairline` | `#D8DFEA` | Borders | 1.24 : 1 | 1.34 : 1 | Decorative only; never the sole boundary of a control |
| `--color-success` | `#0F6B31` | Success text and icons | 6.13 : 1 | 6.63 : 1 | Pass AA |
| `--color-warning` | `#9A4B00` | Warning text and icons | 5.74 : 1 | 6.21 : 1 | Pass AA |
| `--color-danger` | `#B0201F` | Error text, destructive | 6.32 : 1 | 6.84 : 1 | Pass AA |

**Text on accent fill:** `--color-ink` on `--color-accent` is **5.76 : 1** — passes.
The previous system put `--color-ground` on `--color-accent`, which is 2.40 : 1 and
fails; that was the primary button, so every primary button in the product failed AA
while the accessibility section claimed a 4.5:1 floor. Ink on accent is the only
approved combination.

## Colour — Dark

```css
@media (prefers-color-scheme: dark) {
  :root {
    --color-ground:        #12161C;
    --color-surface:       #1B212B;
    --color-ink:           #E6EAF2;
    --color-muted-ink:     #8B98AD;
    --color-disabled-ink:  #5C6878;
    --color-accent:        #D3DE84; /* fill only */
    --color-accent-hover:  #C2CE6E;
    --color-accent-active: #B1BD5C;
    --color-accent-strong: #D3DE84; /* on dark, the fill colour is already text-safe */
    --color-hairline:      #2E3746;
    --color-success:       #4ADE80;
    --color-warning:       #FBBF24;
    --color-danger:        #FF7B72;
    --color-on-danger:     #12161C; /* dark ink: white on this fill is 2.52:1 */
  }
}
```

| Token | Hex | On ground | Verdict |
|---|---|---|---|
| `--color-surface` | `#1B212B` | 1.12 : 1 | Separation only, with hairline |
| `--color-ink` | `#E6EAF2` | 15.05 : 1 | Pass |
| `--color-muted-ink` | `#8B98AD` | 6.22 : 1 | Pass |
| `--color-disabled-ink` | `#5C6878` | 3.20 : 1 | Disabled only |
| `--color-accent` | `#D3DE84` | 12.57 : 1 | Pass as text and as ring |
| `--color-danger` | `#FF7B72` | 7.20 : 1 | Pass as text |
| `--color-on-danger` | `#12161C` | — | Text on the danger fill: 7.20 : 1. Must **not** be white here — white on this fill is 2.52 : 1 |
| `--color-success` | `#4ADE80` | 10.41 : 1 | Pass |
| `--color-warning` | `#FBBF24` | 10.87 : 1 | Pass |

Dark text on accent fill: `#12161C` on `#D3DE84` is **12.57 : 1**; on the hover and
active fills, 10.67 : 1 and 8.90 : 1.
Muted vs accent separation is **2.02 : 1** — they are distinguishable. In the
previous system `--color-muted-ink`, `--color-accent` and the focus ring were all
`#A0AA54`, making secondary text, disabled text and the interactive accent the same
colour. The old dark palette also had `--color-danger #DC3545` at **4.14 : 1**,
below AA; that is fixed above.

## Typography

```css
--font-sans: "Space Grotesk", system-ui, -apple-system, "Segoe UI", sans-serif;
--font-mono: "IBM Plex Mono", ui-monospace, Menlo, monospace;

:root {
  --scale-0: 0.75rem;   /* 12px */
  --scale-1: 0.875rem;  /* 14px */
  --scale-2: 1rem;      /* 16px */
  --scale-3: 1.125rem;  /* 18px */
  --scale-4: 1.25rem;   /* 20px */
  --scale-5: 1.5rem;    /* 24px */
  --scale-6: 2rem;      /* 32px */
}
```

| Role | Size | Weight | Line-height | Letter-spacing |
|---|---|---|---|---|
| display | `--scale-6` | 700 | 1.2 | -0.02em |
| h1 | `--scale-5` | 600 | 1.3 | -0.01em |
| h2 | `--scale-4` | 600 | 1.35 | 0 |
| body | `--scale-2` | 400 | 1.5 | 0 |
| small | `--scale-1` | 400 | 1.4 | 0.01em |
| mono | `--scale-1` | 400 | 1.5 | 0 |

Timecodes always use `--font-mono` so digits do not shift width as they tick.

## Spacing & Layout

```css
:root {
  --spacing-1: 0.25rem; --spacing-2: 0.5rem;  --spacing-3: 0.75rem;
  --spacing-4: 1rem;    --spacing-5: 1.5rem;  --spacing-6: 2rem;
  --spacing-8: 3rem;

  --container-md: 768px;
  --container-lg: 1024px;
  --container-xl: 1280px;

  --grid-columns: 12;
  --grid-gutter: var(--spacing-4);

  --breakpoint-sm: 640px;
  --breakpoint-md: 768px;
  --breakpoint-lg: 1024px;

  --section-rhythm: var(--spacing-8); /* vertical gap between major regions */
  --target-min: 44px;                 /* minimum interactive size */
}
```

## Radius, Border & Elevation

```css
:root {
  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 12px;
  --border-width: 1px;

  --elevation-1: 0 1px 3px rgba(22, 41, 75, 0.10);
  --elevation-2: 0 4px 10px rgba(22, 41, 75, 0.13);
  --elevation-3: 0 12px 24px rgba(22, 41, 75, 0.16);
}
```

## Motion — UI only

```css
:root {
  --duration-fast: 100ms;
  --duration-medium: 200ms;
  --duration-slow: 400ms;

  --ease-out:    cubic-bezier(0, 0, 0.2, 1);
  --ease-in:     cubic-bezier(0.4, 0, 1, 1);
  --ease-in-out: cubic-bezier(0.4, 0, 0.2, 1);
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}
```

| Interaction | Duration | Easing |
|---|---|---|
| Button hover / press | `--duration-fast` | `--ease-out` |
| Dialog open / close | `--duration-medium` | `--ease-in-out` |
| Timeline handle drag | none (follows pointer) | — |
| Toast in / out | `--duration-medium` | `--ease-in-out` |
| Stage progress advance | `--duration-slow` | `--ease-out` |

`--duration-medium` was changed from 250ms to 200ms so the whole scale is a whole
number of frames at 30 fps, which matters because the preview player and the
rendered output should behave the same. 250ms is 7.5 frames.

## Caption Output Tokens

**This block was missing, and without it the renderer cannot be written**, because
`rules.md` forbids any hex, size or duration outside the token set. These are the
tokens for the burned-in captions in the exported video. They are **not** CSS —
they are the values the ASS generator emits — but they are defined here so there is
one source of truth for the product's visual identity.

```
/* Geometry — authored for a 1080 × 1920 frame */
caption.font-family        "Montserrat ExtraBold", "DejaVu Sans Bold"
caption.font-size          84px          /* 4.4% of frame height */
caption.line-height        1.15
caption.case               uppercase
caption.max-words-per-line 3
caption.max-lines          2
caption.safe-area-bottom   420px         /* clears platform UI overlays */
caption.safe-area-x        90px

/* Colour — see the legibility note below */
caption.color-inactive     #FFFFFF
caption.color-active       #F2E14C
caption.stroke-color       #0A0A0A
caption.stroke-width       8px
caption.shadow             0 4px 12px rgba(10, 10, 10, 0.55)

/* Motion — video scale, frame-quantised at 30 fps */
caption.pop-duration       100ms         /* 3 frames */
caption.pop-scale-from     0.88
caption.pop-scale-to       1.06
caption.settle-duration    67ms          /* 2 frames, 1.06 back to 1.00 */
caption.fade-in            67ms          /* 2 frames */
caption.word-advance       from Whisper word timings — never a fixed interval
```

**Legibility over arbitrary video.** WCAG contrast ratios assume a known
background. Captions sit on whatever frame is behind them, so the guarantee comes
from structure, not a ratio: every glyph carries an 8px opaque stroke plus a
shadow, so the effective contrast is text against `caption.stroke-color`, which is
**19.80 : 1** for inactive words and **14.75 : 1** for the active word. The stroke
is not decorative and must not be reduced.

**The active word is signalled twice** — colour *and* the pop scale. Active versus
inactive is only 1.34 : 1 in luminance, so colour alone would not read for a
viewer with a colour vision deficiency, and would vanish on a yellow-ish frame.

**Why a separate motion scale.** The UI tokens are wrong for video on two counts:
they are authored for an event-driven compositor that can render at any moment,
and 250ms is 7.5 frames at 30 fps, which judders when baked into a fixed frame
grid. Caption durations are whole frames. Word advance is never a fixed interval —
it comes from the Whisper word timings, which is the entire point of the feature.

## Components

Every interactive component is ≥ `--target-min` in both dimensions and has a
`:focus-visible` state. States marked "same" inherit the row above.

### Button

| State | Background | Text | Border | Shadow |
|---|---|---|---|---|
| default | `--color-accent` | `--color-ink` (5.76 : 1) | none | `--elevation-1` |
| hover | `--color-accent-hover` | same (5.00 : 1) | none | `--elevation-2` |
| active | `--color-accent-active` | same (4.74 : 1) | none | `--elevation-1` |
| focus-visible | same as default | same | `2px solid --color-accent-strong`, `outline-offset: 2px` | `--elevation-2` |
| disabled | `--color-hairline` | `--color-disabled-ink` (2.64 : 1, exempt) | none | none |
| destructive | `--color-danger` | `--color-on-danger` (6.84 : 1 light, 7.20 : 1 dark) | none | `--elevation-1` |

### Input

| State | Background | Text | Border |
|---|---|---|---|
| default | `--color-surface` | `--color-ink` | `1px solid --color-hairline` |
| hover | same | same | `1px solid --color-muted-ink` |
| focus-visible | same | same | `2px solid --color-accent-strong`, `outline-offset: 2px` |
| disabled | `--color-ground` | `--color-disabled-ink` | `1px solid --color-hairline` |
| error | same | same | `2px solid --color-danger` + message text in `--color-danger` |

### Card

| State | Background | Border | Shadow |
|---|---|---|---|
| default | `--color-surface` | `1px solid --color-hairline` | `--elevation-1` |
| hover | same | same | `--elevation-2` |

### ClipTimeline (product-specific)

The draggable start/end editor. This component is why the PRD settled on FastAPI
with a hand-written page rather than Streamlit — it is not expressible there, and
the interaction is core product rather than polish. The spec below is therefore
binding, not aspirational.

| Part | Spec |
|---|---|
| Track | Height 56px, `--color-ground`, `--radius-md` |
| Selected span | `--color-accent` at 30% alpha, `2px solid --color-accent-strong` |
| Handle | 44 × 56px hit area, 6px visible bar in `--color-accent-strong` |
| Handle focus-visible | `2px solid --color-ink`, `outline-offset: 2px` |
| Handle keyboard | `←`/`→` nudge 100ms, `Shift` + arrow nudge 1s |
| Out-of-range state | Track border `--color-danger`, message naming the 15–60s rule |
| Timecode labels | `--font-mono`, `--scale-1`, `--color-muted-ink` |

Dragging must be operable by keyboard, which is why the handles are focusable
controls with arrow-key semantics rather than pointer-only affordances.

## Accessibility

- **Contrast floor:** 4.5:1 for body text, 3:1 for non-text UI indicators and
  focus rings (WCAG 2.2 §1.4.11). Every token above states its measured ratio.
  `--color-accent` fails as text and is therefore fill-only; `--color-accent-strong`
  exists to be the text-and-ring counterpart. The old focus ring used the 2.40:1
  accent, below the 3:1 requirement.
- **Minimum target:** 44 × 44px, `--target-min`.
- **Focus ring:** `2px solid --color-accent-strong` with `outline-offset: 2px`,
  never removed without an equivalent replacement.
- **Keyboard:** logical DOM order; dialogs trap focus; the timeline handles are
  reachable and adjustable by arrow keys.
- **Colour independence:** no state is signalled by colour alone, in the UI or in
  the captions.
- **ARIA:**
  - URL field — native `<input type="url">` with `<label>`. Do not add
    `role="textbox"` to a native input; it is redundant and can override the
    implicit role.
  - Stage progress — `role="status"` `aria-live="polite"`, announcing stage name
    and elapsed time, not a percentage that changes every frame.
  - Timeline handles — `role="slider"` with `aria-valuemin`, `aria-valuemax`,
    `aria-valuenow` in seconds and `aria-valuetext` as a human timecode.
  - Preview region — `role="region"` `aria-label="Clip preview"`.
- **Reduced motion:** honoured throughout the UI. It does **not** apply to the
  rendered video, which is a media file rather than an interface; a viewer's OS
  setting cannot reach it, and the caption animation is the product.
