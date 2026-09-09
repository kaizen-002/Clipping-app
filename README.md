# Local Podcast Shorts Generator

Paste a podcast episode URL. It finds the most clippable 15–60 seconds, times
every word, burns in animated captions, and writes a vertical MP4 — entirely on
your machine. No cloud inference, no account, no upload of your audio.

## Status

49 unit tests pass, covering the validation ladder, the caption timing
invariants, progress tracking, retention and the ASS output.

**Measured on a 12-core CPU**, models cached: survey transcription runs at
~14x realtime, the precise word-timing pass at ~1.9x, and a windowed video
fetch takes ~43s. A 30-minute episode is roughly 4.5 minutes of work.

The first run is slower and always will be: it downloads ~1.6 GB of Whisper
models. That download now reports a percentage instead of sitting silent,
which is what made it look like a hang.

Ollama with Llama 3 is installed and working: hook detection takes ~9 s on a
30-minute episode. It remains optional — without it the deterministic heuristic
picks the clips and the UI labels them as such.

With the transcript cached, a full re-run of a 30-minute episode is **78.7 s**.

## Install

Requires Python 3.11+, plus two external binaries that are not pip-installable:

- **FFmpeg** with libass, **ffprobe**, and **yt-dlp** — drop the `.exe` files in
  `bin/` and they are found automatically, ahead of anything on PATH.
  Keep yt-dlp current (`bin/yt-dlp.exe -U`). YouTube changes how it serves
  media, and an out-of-date build fails with `HTTP Error 403: Forbidden`.
  This is why yt-dlp is the one unpinned dependency.
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
| 1 | Fetch **audio only** | Tens of MB instead of ~1 GB. Nothing before the hooks needs pixels |
| 2 | Survey-transcribe the episode with `base` | Enough to find hooks; word timing not bought yet |
| 3 | Score and rank the top N segments | Llama 3 if present, else the deterministic heuristic |
| 4 | Precise-transcribe **only the chosen windows** | Word timing for 3x60s, not 3,600s |
| 5 | Fetch **only those windows** of video | `yt-dlp --download-sections` |
| 6 | Generate the ASS caption track | One timed event per word |
| 7 | Burn in and encode | Only after you have picked a clip and edited it |

Stage 2 alone is ~45% of the wall clock, and it runs once no matter how many
clips are requested. Stages 4 and 5 scale with the clip count.

## The three rules worth knowing before you edit the code

**Word timings are measurements, not text properties.** They came from the
audio. Editing a caption cannot regenerate them. Deleting a word keeps the rest
in sync; inserting one splits its neighbour's interval; *rewriting* a word is
rejected, because the new timing would be a guess and a guessed timing
desynchronises the caption from the speech. This is enforced in
`clipping/core/editing.py`, not in the browser.

**The heuristic fallback is never dressed up as a model judgement.** When the
LLM's answer fails validation twice, a deterministic scan picks the clips and the
UI says so in a badge. A silent fallback would mean nobody ever learns the model
is failing.

**Progress comes from the tool doing the work, never a timer.** yt-dlp's own
percentage, Whisper's segment position, FFmpeg's frame counter. A bar that
advances on a clock is worse than no bar, because it teaches the user to
distrust it.

**Subprocesses merge stderr into stdout.** Draining one pipe while the other
fills its 64 KB buffer deadlocks the child. This cost a 23-minute silent hang
before it was found; see `_run` in `clipping/adapters/ytdlp_source.py`.

## Layout

```
clipping/core/       Pure logic. No network, no subprocess, no file I/O.
clipping/adapters/   The four edges: yt-dlp, faster-whisper, Ollama, FFmpeg.
clipping/web/        FastAPI + one static page.
docs/                PRD.md and rules.md are binding. design.md is superseded;
                     its caption tokens and accessibility floors still hold.
scripts/contrast.py  Verifies every colour pair. Exits non-zero on failure.
```

The four ports in `core/ports.py` are a closed set, justified by testability
today rather than imagined future flexibility. A fifth needs a recorded
decision — see `docs/rules.md`.

## Checks

```bash
python -m pytest tests -q      # 49 tests, no external binaries needed
python scripts/contrast.py     # every colour pair, light and dark
```

`scripts/contrast.py` exists because the original design document's contrast
table was written by hand rather than computed, and every value in it was wrong
— including the ones marked as passing. Numbers that matter get computed.

## Deliberately not here

No publishing APIs, no cloud inference, no accounts, no batch export, no custom
animation builder, no non-English support, no speaker diarisation, no face
tracking. See `docs/PRD.md` "Out of Scope" — those are decisions, not gaps.
