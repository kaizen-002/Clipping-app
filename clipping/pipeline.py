"""The staged pipeline, wired from ports.

Order matters and is the whole point of the design: audio first, survey
transcribe, choose the hook, then buy word-level timing and video pixels for
the chosen 15-60 seconds only.

Every stage is timed into work/run_log.jsonl. The budget table in PRD.md is
engineering estimates; this is where the measurements that replace it come from.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from clipping.config import DEFAULT_PATHS, Paths
from clipping.core import captions
from clipping.core.hooks import HookRejected, heuristic_hook, validate_candidate
from clipping.core.models import Clip, HookSelection, StageTiming, Transcript
from clipping.core.ports import HookFinder, MediaSource, Renderer, Transcriber
from clipping.retention import clear_work, prune_input

ProgressHook = Callable[[str, str], None]
"""Called as (stage_name, human_detail) when a stage begins."""


@dataclass
class RunResult:
    """Everything a run produced, including how long each stage took."""

    clip: Clip
    video_path: Path
    ass_path: Path
    srt_path: Path
    output_path: Path | None
    timings: list[StageTiming] = field(default_factory=list)

    @property
    def total_seconds(self) -> float:
        return sum(timing.seconds for timing in self.timings)


class Pipeline:
    """Composes the four ports. Holds no I/O of its own beyond the run log."""

    def __init__(
        self,
        source: MediaSource,
        transcriber: Transcriber,
        hook_finder: HookFinder,
        renderer: Renderer,
        paths: Paths = DEFAULT_PATHS,
        progress: ProgressHook | None = None,
    ) -> None:
        self._source = source
        self._transcriber = transcriber
        self._hook_finder = hook_finder
        self._renderer = renderer
        self._paths = paths.ensure()
        self._progress = progress or (lambda stage, detail: None)
        self._timings: list[StageTiming] = []

    def prepare(self, url: str) -> RunResult:
        """Run stages 1-6: everything up to the point the user can edit.

        Rendering is deliberately not here. The user edits bounds and caption
        text first, and only then pays for an encode.
        """
        self._timings = []
        prune_input(self._paths.input_dir)
        slug = _slug(url)

        with self._stage("1. Audio fetch"):
            duration = self._source.probe_duration(url)
            audio = self._source.fetch_audio(url, self._paths.input_dir / f"{slug}-audio")

        with self._stage("2. Survey transcription"):
            transcript = self._transcriber.survey(audio)
            if transcript.source_duration <= 0:
                transcript = transcript.model_copy(update={"source_duration": duration})

        with self._stage("3. Hook detection"):
            selection = self._select_hook(transcript)

        with self._stage("4. Precise transcription"):
            words = self._transcriber.precise(audio, selection.start, selection.end)

        with self._stage("5. Windowed video fetch"):
            video = self._source.fetch_video_window(
                url, selection.start, selection.end, self._paths.input_dir / f"{slug}-clip"
            )

        clip = Clip(
            source_url=url,
            start=selection.start,
            end=selection.end,
            words=words,
            origin=selection.origin,
            reason=selection.reason,
            truncated=selection.truncated,
        )

        with self._stage("6. Caption generation"):
            ass_path, srt_path = self.write_caption_files(clip, slug)

        return RunResult(
            clip=clip,
            video_path=video,
            ass_path=ass_path,
            srt_path=srt_path,
            output_path=None,
            timings=list(self._timings),
        )

    def write_caption_files(self, clip: Clip, slug: str) -> tuple[Path, Path]:
        """Write the ASS animation source and the SRT upload sidecar.

        Called again after every edit, because the caption files are derived
        from the clip and must never drift from it.
        """
        ass_path = self._paths.work_dir / f"{slug}.ass"
        srt_path = self._paths.output_dir / f"{slug}.srt"
        ass_path.write_text(captions.build_ass(clip.words, clip.start), encoding="utf-8")
        srt_path.write_text(captions.build_srt(clip.words, clip.start), encoding="utf-8")
        return ass_path, srt_path

    def export(self, result: RunResult, slug: str | None = None) -> RunResult:
        """Stage 8: burn in and encode.

        Split from `prepare` so an edit costs a caption rebuild, not a re-fetch.
        """
        name = slug or _slug(result.clip.source_url)
        ass_path, srt_path = self.write_caption_files(result.clip, name)
        destination = self._paths.output_dir / f"{name}.mp4"

        # The fetched window carries padding, so the burn-in cut is relative to
        # where that window actually began rather than to the episode.
        window_offset = max(result.clip.start - 2.0, 0.0)
        local_start = result.clip.start - window_offset
        local_end = local_start + result.clip.duration

        with self._stage("7. Render"):
            output = self._renderer.render(
                result.video_path, ass_path, local_start, local_end, destination
            )

        clear_work(self._paths.work_dir)
        self._write_run_log(result.clip.source_url, output)

        return RunResult(
            clip=result.clip,
            video_path=result.video_path,
            ass_path=ass_path,
            srt_path=srt_path,
            output_path=output,
            timings=list(self._timings),
        )

    def _select_hook(self, transcript: Transcript) -> HookSelection:
        """The failure path from PRD.md: retry once, then the heuristic.

        Never silently past a failure — each rejection is carried into the next
        attempt and, if both fail, surfaced on the result as `origin`.
        """
        try:
            candidate = self._hook_finder.find(transcript)
            outcome = validate_candidate(candidate, transcript)
            return HookSelection(
                start=outcome.start,
                end=outcome.end,
                reason=candidate.reason,
                origin="llm",
                truncated=outcome.truncated,
            )
        except (HookRejected, Exception) as first_error:  # noqa: BLE001
            # Broad on purpose: an adapter can fail in ways the core cannot
            # enumerate (socket reset, model unloaded, malformed JSON), and
            # every one of them must reach the retry rather than the user.
            first_reason = str(first_error)
            self._progress("3. Hook detection", f"retrying — {first_reason}")

        retry = getattr(self._hook_finder, "find_with_schema_restated", None)
        if retry is not None:
            try:
                candidate = retry(transcript, first_reason)
                outcome = validate_candidate(candidate, transcript)
                return HookSelection(
                    start=outcome.start,
                    end=outcome.end,
                    reason=candidate.reason,
                    origin="llm-retry",
                    truncated=outcome.truncated,
                )
            except Exception as second_error:  # noqa: BLE001 - same reasoning
                self._progress(
                    "3. Hook detection", f"falling back to heuristic — {second_error}"
                )

        return heuristic_hook(transcript)

    @contextmanager
    def _stage(self, name: str):
        """Time a stage and announce it."""
        self._progress(name, "")
        started = time.monotonic()
        try:
            yield
        finally:
            elapsed = time.monotonic() - started
            self._timings.append(StageTiming(stage=name, seconds=elapsed))

    def _write_run_log(self, url: str, output: Path) -> None:
        """Append measured stage times. This is what replaces the estimates."""
        log_path = self._paths.work_dir.parent / "work" / "run_log.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "url": url,
            "output": str(output),
            "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "total_seconds": round(sum(t.seconds for t in self._timings), 2),
            "stages": {t.stage: round(t.seconds, 2) for t in self._timings},
        }
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")


def _slug(url: str) -> str:
    """A filesystem-safe stem derived from the URL.

    Not a hash: seeing the video id in `input/` is what makes a stalled run
    diagnosable by looking at the folder.
    """
    tail = url.rstrip("/").split("/")[-1]
    if "v=" in tail:
        tail = tail.split("v=")[-1].split("&")[0]
    safe = "".join(char if char.isalnum() or char in "-_" else "-" for char in tail)
    return safe[:48] or "clip"
