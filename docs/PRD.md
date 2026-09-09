# PRD — Local Podcast Shorts Generator

> **The three open decisions are settled.** The chosen options are recorded in
> **Decisions Made** at the end, with the rejected alternative and the reason, so
> the tradeoff stays legible later. The document below reflects the decisions; it
> no longer presents both paths.

## Problem

Turning a long podcast recording into a short vertical clip means watching the
whole thing to find a good moment, transcribing it, styling captions, and
rendering — across several disconnected tools. It is slow, repetitive, and the
transcription step usually costs money per minute of audio.

## Users

**Primary:** A solo podcaster who edits their own show and wants captioned
vertical clips for TikTok, Shorts and Reels, running everything on their own
machine so no audio leaves it and there is no per-minute cost.

**Secondary:** None. Anything a second user type would need is out of scope.

## Goals

- Find a defensible hook segment in a full episode without the user watching it.
- Produce word-level captions accurate enough to publish without hand-fixing.
- Let the user correct the clip boundaries and caption text before export.
- Run all inference locally, with no audio or transcript sent off the machine.
- Finish in a time the user will actually wait through. See the budget below.

## MVP Scope

1. **Audio-First Import** — User pastes a YouTube URL. The app fetches the
   **audio stream only** for analysis, not the full video.
   *Acceptance:* Downloaded audio duration matches the source within ±1 s, and no
   video stream is fetched during this step.
   *Rationale:* audio for a 1-hour episode is tens of megabytes against roughly a
   gigabyte for 1080p video. Nothing before the hook is chosen needs the pixels.

2. **Survey Transcription** — Transcribes the full episode audio with a small
   Whisper model to produce a segment-level transcript for hook-finding.
   *Acceptance:* A transcript covering ≥99% of the episode duration is produced,
   with segment timestamps within ±2 s. Word-level timing is **not** required here.

3. **Hook Detection** — Sends the survey transcript to a local Llama 3 via Ollama,
   which returns a candidate segment.
   *Acceptance:* The model returns JSON validated against the `HookCandidate`
   contract below. On validation failure the app retries once with the schema
   restated; on a second failure it falls back to the highest-scoring segment from
   the deterministic heuristic and labels the result as such in the UI. The
   returned span is clamped to 15–60 s and to the episode bounds before use.

4. **Precise Transcription of the Hook** — Re-transcribes **only the chosen
   15–60 s window** with a larger Whisper model and word timestamps on.
   *Acceptance:* Every word in the window carries a start and end time, and word
   boundaries fall within ±0.15 s of the audio on a hand-checked sample.
   *Rationale:* word-level accuracy is only needed for the seconds that ship.
   Buying it for the whole hour is the single largest cost in the pipeline.

5. **Clip Video Fetch** — Fetches the video for the chosen window only, using
   `yt-dlp --download-sections`.
   *Acceptance:* The fetched file covers the chosen window plus ≤2 s of padding at
   each end, and is not a full-episode download.

6. **Caption Styling** — Generates a per-word animated caption track in **ASS**
   format from the precise transcript, using the tokens in `design.md`.
   *Acceptance:* The `.ass` file contains one timed event per word, and the active
   word is styled distinctly from inactive words in the same line.
   SRT cannot express this; see **Decisions Made 3**.

7. **Interactive Preview & Editing** — Shows the clip with captions. The user can
   adjust the start and end and edit caption text.
   *Acceptance:* every invariant in **Editor Invariants** below holds, and the
   export reflects the edited values.

8. **Styled Clip Export** — Renders to MP4 with FFmpeg, burning in the ASS track.
   *Acceptance:* Audio and video stay in sync end to end (drift ≤80 ms measured at
   the final word), output duration equals the edited window ±0.2 s, and the file
   is encoded at the settings named in **Encoding Settings**.

### `HookCandidate` output contract

The LLM must return exactly this, and nothing else:

```json
{ "clips": [{ "start_seconds": 812.4, "end_seconds": 851.9, "reason": "one sentence" }] }
```

Three things about this are load-bearing, all established by measurement
against Llama 3 8B on a 30-minute episode:

1. **The transcript sent to the model is merged into ~25 s chunks.** Raw, a
   half-hour episode is 874 segments and ~8,900 tokens, and at that length the
   model stopped obeying the schema and echoed prompt fragments back as JSON
   keys. Merged, it is 72 segments and ~5,500 tokens. Chunk boundaries are real
   segment boundaries, so rung 4 still holds.
2. **Decoding is constrained by a JSON schema, not by asking for "json".**
   Asked for `format: "json"` on this prompt the model returned `{}`.
3. **The schema bounds the array with `maxItems`.** Unbounded, one request ran
   past ten minutes; bounded, the same request takes about ten seconds.

Clips must also be separated by at least 20 s. Adjacency is not overlap: the
model returned 1276-1301 and 1301-1325, which pass an overlap test and are one
continuous stretch of talk.

Validation, in order — any failure moves to the next step, never silently past it:

1. Parses as JSON and matches the Pydantic model.
2. `0 ≤ start < end ≤ episode_duration`.
3. `15 ≤ (end - start) ≤ 60`. If longer, truncate to the first 60 s and mark it
   truncated. If shorter, reject.
4. Both timestamps land inside a real transcript segment. Timestamps falling in a
   gap are hallucinated and rejected.

Failure path: retry once → deterministic heuristic fallback → surface to the user.
The heuristic is a scored scan of the survey transcript (speech density, question
marks, laughter markers) and exists so the pipeline never dead-ends on a bad
generation.

### Editor Invariants

Enforced in the domain layer, not only in the UI:

- `end > start`, and both lie within the fetched clip.
- `15 s ≤ (end - start) ≤ 60 s`.
- No caption line is empty.
- **Editing caption text preserves word timings.** Word timings come from Whisper
  and cannot be regenerated from edited text. On edit: an unchanged word count
  remaps timings positionally; a deleted word drops its timing; an inserted word
  splits the neighbouring word's interval evenly. Any edit that would leave a word
  without a timing is rejected with a message saying so. This is the invariant most
  likely to be broken by a naive implementation, because the caption text and the
  timing array look independent and are not.
- Adjusting start or end drops words outside the new bounds rather than rescaling
  the remaining timings.

### Decisions Made 4 — clip count

**DECIDED: a run returns the top N ranked segments, default 3, maximum 5.**

*Was:* "Multiple hooks per episode. One segment per run." — listed under Out of
Scope.

*Why it changed:* a ranked list is the product. One clip per run makes the
results screen a single card and gives the user nothing to choose between,
which is the difference between a tool and a batch script.

*Cost:* stages 4 and 5 now run once per clip, so they scale with N. Stage 2,
which dominates the wall clock, does not — the survey transcript is read once
and scored N times. Candidates are validated individually, so one bad span
costs that span rather than the run.

*Rejected:* one segment per run. Simpler, and already built, but it is the
single biggest gap between this and the tools it sits beside.

## Out of Scope

- **Direct social publishing.** No TikTok, YouTube or Instagram API integration.
- **Cloud or remote inference.** No hosted model endpoints for transcription or
  hook detection. See Hard Constraints for the precise wording.
- **Authentication and multi-user profiles.** Single user, single machine.
- **Custom animation builder.** One bundled caption style, not user-authored.
- **Batch processing.** One episode per run.
- **Non-English audio.** English only in v1.
- **Sources other than YouTube.** No local file import, no RSS, no other hosts.
- **Speaker diarisation.** Captions do not attribute lines to speakers.
- **Vertical reframing or face tracking.** Fixed centre crop to 9:16, no subject
  tracking.

## Technical Requirements

**Stack:** Python 3.11. FFmpeg with libass. `yt-dlp`. `faster-whisper`. Ollama
running Llama 3 8B. UI is FastAPI serving one static HTML page with vanilla JS
(**Decisions Made 2**); `design.md` is binding in full — real focus rings, 44px
targets, ARIA as specified.

**Authentication:** None. Local execution only.

**Data storage:** Files on disk. No database. `input/` for fetched media,
`output/` for renders, `work/` for intermediates.

**Retention:** `work/` is cleared at the end of every successful run. `input/`
media older than 7 days, or beyond 5 GB total, is deleted oldest-first at startup.
Without this, hour-long downloads accumulate until the disk fills. `output/` is
never auto-deleted — it holds the user's finished work.

**Hosting:** Local process bound to `127.0.0.1`. Not reachable off the machine.

**Third-party services** — every MVP feature maps to a named dependency here:

| Dependency | Serves feature | Notes |
|---|---|---|
| `yt-dlp` | 1, 5 | Audio-only fetch, and `--download-sections` windowed fetch |
| `faster-whisper` | 2, 4 | CTranslate2 int8 on CPU |
| Ollama + Llama 3 8B | 3 | Local HTTP on `127.0.0.1:11434` |
| FFmpeg + libass | 6, 8 | Burn-in of the ASS track, re-encode |

**Hard constraints:**

- **No cloud inference and no third-party data processing.** Transcription and
  hook detection run on the local machine; audio and transcripts are never
  uploaded. The app **does** require internet access to fetch the source video
  from YouTube — that is the one permitted network egress, and it is to the video
  host only.
  *This replaces the earlier "must operate offline", which forbade the app's own
  first feature.*
- Reference hardware: 8 CPU cores, 16 GB RAM, no GPU. A GPU may cut times
  substantially but must not be required.

### Encoding Settings

Fixed, so that output size is a stated consequence rather than an unmeasurable
target: `libx264`, `-crf 20`, `-preset medium`, AAC 192 kbps, 1080×1920, 30 fps.
Burning captions forces a re-encode, so output size follows from these settings and
the clip length — roughly 8–14 MB for 60 s. There is no meaningful "ratio to the
raw clip", because the raw clip is a different resolution, codec and duration.

## Performance Budget

The staged pipeline and the target below are **decided** (**Decisions Made 1**).

**These are measurements, not estimates.** One full run, 30-minute episode,
3 clips, 12 CPU cores, models already cached, audio reused from a previous run:

| Stage | Measured | Note |
|---|---|---|
| 1. Audio fetch | 2.8 s | Reused a cached file; a cold fetch is ~40 s |
| 2. Survey transcription (`base`, int8) | 492.8 s | **3.7x realtime** |
| 3. Hook scoring | 9.0 s | Llama 3 8B on CPU, via Ollama |
| 4. Precise transcription | 133.8 s | 3 windows, ~45 s each |
| 5. Windowed video fetch | 115.0 s | 3 windows, ~38 s each |
| 6. Caption generation | < 0.1 s | String formatting |
| 7. Render (x264 CRF 20, libass) | ~40 s | One clip, 59.2 s output, 28 MB |
| **Total** | **749 s ≈ 12.5 min** | Stage 2 alone is 66% of it |

A second run with the transcript cached and Llama 3 installed totalled **78.7 s**
(audio 3.1, survey 0.0 cached, hook 9.0, precise 34.6, video fetch 23.9,
render 8.1). Caching the survey transcript is what makes re-running an episode
cheap; the first run on a new episode still pays stage 2 in full.

**The earlier 14x-realtime figure for stage 2 was wrong.** It was measured on a
19-second sample, which is far too short to be representative — model warm-up
and VAD behaviour do not amortise the same way. The real figure on a
half-hour episode is 3.7x.

**This misses the target.** At 3.7x, a 1-hour episode spends ~16 minutes in
stage 2 alone and roughly 20 minutes overall, against a p50 of 12. The levers,
in order of effect:

1. `tiny` instead of `base` for the survey pass — roughly halves stage 2, at a
   cost in transcript quality that only affects hook *selection*, never the
   captions, which come from the precise pass.
2. Chunked parallel transcription — faster-whisper is single-job; splitting the
   audio into N pieces across cores is the largest available win and has not
   been attempted.
3. Fewer clips — stages 4 and 5 scale linearly with the count.

**Target: p50 ≤ 12 minutes, p90 ≤ 20 minutes**, over 30 episodes on the reference
hardware. One measured 30-minute run came in at 12.5 minutes, so a 1-hour
episode does not currently meet this. The target stands as a commitment; the
gap above is the work.

The previous target of 5 minutes was not achievable. Transcribing a 1-hour episode
alone exceeds it on 8 CPU cores, before any other stage runs. The audio-first,
two-pass design above is what makes even 12 minutes plausible: it avoids
downloading a gigabyte of video that gets discarded, and buys word-level timing for
60 seconds instead of 3,600.

If a shorter wall-clock is required, the levers in order of effect:

1. Use `tiny` instead of `base` for the survey pass — roughly halves stage 2, at a
   real cost in hook quality, since the LLM reads that transcript.
2. Chunk the transcript and run hook detection as a map-reduce, trading stage 3
   latency for more total compute.
3. Require a GPU, which moves stages 2 and 4 near realtime but breaks the
   "typical consumer laptop" premise.

## Success Metrics

Every metric here is measurable by this application as scoped — single-user, local,
no telemetry, no distribution channel.

- **Pipeline latency.** p50 ≤ 12 min, p90 ≤ 20 min for a 1-hour episode.
  *Measured by:* the app writes per-stage durations to `work/run_log.jsonl` on
  every run; a script aggregates 30 local runs.
- **Hook quality.** On a fixed local set of 20 episodes with hand-marked hooks, the
  returned span reaches ≥0.5 IoU with a marked hook in ≥70% of runs.
  *Measured by:* a checked-in fixture of hand-marked spans plus a comparison script.
  The previous 80% figure had no measurement method attached.
- **Transcription accuracy.** ≤8% WER on a 10-minute hand-corrected reference
  sample, comparing **Whisper output against a human transcript**.
  *Measured by:* `jiwer` against the checked-in reference.
  *This replaces "≤5% WER compared to the Whisper transcript", which compared the
  captions to their own source and could only ever return ~0%.*
- **Caption timing.** On the same reference sample, ≥95% of word boundaries land
  within ±0.15 s of hand-marked positions.
- **Pipeline reliability.** ≤2% of runs end in an unhandled exception across a
  50-run local batch over the fixture set.
  *Measured by:* `scripts/soak.py`, which is in scope and must exist for this
  metric to mean anything.

Deliberately **not** metrics: user satisfaction surveys and adoption figures. The
app is single-user and local and ships no telemetry or update channel, so there is
no mechanism by which it could gather them.

## Decisions Made

All three are settled. Each records the rejected alternative and why, so a later
reader can tell what was traded away rather than assuming nothing was.

**1 — Performance target and pipeline. DECIDED: the staged pipeline.**
Audio-only fetch, survey transcription with `base`, LLM hook detection, word-level
transcription of only the chosen 15–60 s window, then `yt-dlp --download-sections`
for that window alone. Target p50 ≤ 12 min, p90 ≤ 20 min.
*Rejected:* single-pass `small` transcription over the full hour — simpler to build
and roughly 15–25 min, which was judged too slow to sit through.
*What this costs:* more moving parts, and two Whisper model loads per run.
*Still true:* the original 5-minute target was not reachable on CPU at all; that
constraint is what forced the redesign rather than a slower single pass.

**2 — UI stack. DECIDED: FastAPI serving one static HTML page with vanilla JS.**
The draggable start/end timeline is core product, not polish: interaction quality
is the differentiator, and numeric start/end inputs would make this a form rather
than a tool. `design.md` is therefore binding in full — real focus rings, 44px
targets, and the ARIA specified there.
*Rejected:* Streamlit. It re-runs the script on interaction, has no timeline
widget, and does not expose focus styling or ARIA at that level, so Streamlit and
`design.md` could not both be satisfied.
*What this costs:* the UI is hand-written rather than generated, so form handling,
state and progress streaming are all explicit work.

**3 — Caption format. DECIDED: ASS burned in via libass, SRT as a sidecar.**
ASS carries per-word events and styling, and FFmpeg burns it in through libass with
no extra dependency. SRT ships only as a line-level sidecar for platform upload and
is never described as the source of the animation.
*Rejected:* frame-by-frame rendering with PIL — total control, far slower, much
more code. Also rejected: SRT as the caption source, which cannot express per-word
timing or styling at all and made two of the original acceptance criteria mutually
impossible.
*What this costs:* caption styling is expressed in ASS override tags rather than
anything more readable.

## Open Questions

- Which bundled caption style ships as the default? `design.md` defines tokens for
  one; wanting more reopens "Custom Animation Builder" in Out of Scope.
- Should the survey transcript be cached per video ID so a re-run skips stage 2?
  It would make iteration much faster and adds cache invalidation.
- What should happen when the episode is shorter than 15 s, or has no speech?
