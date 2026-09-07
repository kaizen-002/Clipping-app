# Local Podcast Shorts Generator

Paste a podcast episode URL. It finds the most clippable 15–60 seconds, times
every word, burns in animated captions, and writes a vertical MP4 — entirely on
your machine. No cloud inference, no account, no upload of your audio.

## Status

The pipeline, the domain rules and the editor UI are written and unit-tested.
**The end-to-end run has not been executed yet**, because `ffmpeg` and `ollama`
are not installed on this machine. Until someone runs it against a real episode,
treat the performance numbers in `docs/PRD.md` as engineering estimates — which
is what they are labelled as.

31 unit tests pass, covering the validation ladder, the caption timing
invariants and the ASS output. Those do not need the external binaries.

## Install

Requires Python 3.11+, plus two external binaries that are not pip-installable:

- **FFmpeg**, built with libass (`ffmpeg -filters | grep ass` should list it)
- **Ollama**, with Llama 3 pulled: `ollama pull llama3`

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows
pip install -r requirements.txt
```

## Run

Terminal, which is the honest way to measure it:

```bash
python -m clipping.cli "https://www.youtube.com/watch?v=..."
```

The page, which is the way to edit it:

```bash
python -m clipping.web.app
```

Then open `http://127.0.0.1:8000`. The server binds to localhost only and is not
reachable from other machines.

## How it works

The order of the stages is the whole design. A naive pipeline downloads a
gigabyte of video and buys word-level transcription for 3,600 seconds, then
throws away 98% of both.

| Stage | What it does | Why here |
|---|---|---|
| 1 | Fetch **audio only** | Tens of MB instead of ~1 GB. Nothing before the hook needs pixels |
| 2 | Survey-transcribe the hour with `base` | Enough to find a hook; word timing not bought yet |
| 3 | Llama 3 picks the hook | Validated, retried once, then a deterministic fallback |
| 4 | Precise-transcribe **only the chosen window** | Word timing for 60s, not 3,600s |
| 5 | Fetch **only that window** of video | `yt-dlp --download-sections` |
| 6 | Generate the ASS caption track | One timed event per word |
| 7 | Burn in and encode | Only after you have edited |

Stages 2 and 3 are roughly 85% of the wall clock.

## The two rules worth knowing before you edit the code

**Word timings are measurements, not text properties.** They came from the
audio. Editing a caption cannot regenerate them. Deleting a word keeps the rest
in sync; inserting one splits its neighbour's interval; *rewriting* a word is
rejected, because the new timing would be a guess and a guessed timing
desynchronises the caption from the speech. This is enforced in
`clipping/core/editing.py`, not in the browser.

**The heuristic fallback is never dressed up as a model judgement.** When the
LLM's answer fails validation twice, a deterministic scan picks the clip and the
UI says so in a badge. A silent fallback would mean nobody ever learns the model
is failing.

## Layout

```
clipping/core/       Pure logic. No network, no subprocess, no file I/O.
clipping/adapters/   The four edges: yt-dlp, faster-whisper, Ollama, FFmpeg.
clipping/web/        FastAPI + one static page.
docs/                PRD.md, design.md, rules.md — binding, not decorative.
scripts/contrast.py  Verifies every colour pair. Exits non-zero on failure.
```

The four ports in `core/ports.py` are a closed set, justified by testability
today rather than imagined future flexibility. A fifth needs a recorded
decision — see `docs/rules.md`.

## Checks

```bash
python -m pytest tests -q      # 31 tests, no external binaries needed
python scripts/contrast.py     # every colour pair, light and dark
```

`scripts/contrast.py` exists because the original design document's contrast
table was written by hand rather than computed, and every value in it was wrong
— including the ones marked as passing. Numbers that matter get computed.

## Deliberately not here

No publishing APIs, no cloud inference, no accounts, no batch mode, no custom
animation builder, no non-English support, no speaker diarisation, no face
tracking. See `docs/PRD.md` "Out of Scope" — those are decisions, not gaps.
