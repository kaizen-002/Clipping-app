"""The staged pipeline, wired from ports.

Order matters and is the whole point of the design: audio first, survey
transcribe, choose the hooks, then buy word-level timing and video pixels for
the chosen 15-60 second windows only.

Every stage reports real progress from the tool doing the work, and is timed
into work/run_log.jsonl. The budget table in PRD.md started as engineering
estimates; this is where the measurements that replace it come from.
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from clipping.config import DEFAULT_PATHS, Paths, resolve_executable
from clipping.core import captions
from clipping.core.boundaries import is_well_formed, snap_to_sentences
from clipping.core.hooks import (
    HookRejected,
    conflicts_with,
    heuristic_hooks,
    validate_candidate,
)
from clipping.core.models import Clip, ClipSet, HookSelection, StageTiming, Transcript
from clipping.core.ports import HookFinder, MediaSource, Renderer, Transcriber
from clipping.core.progress import ProgressSink, ProgressTracker
from clipping.retention import clear_work, prune_input

DEFAULT_CLIP_COUNT = 3


@dataclass
class RunResult:
    """Everything a run produced, including how long each stage took."""

    clip_set: ClipSet
    video_paths: list[Path]
    output_paths: dict[int, Path] = field(default_factory=dict)
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
        progress: ProgressSink | None = None,
        clip_count: int = DEFAULT_CLIP_COUNT,
    ) -> None:
        self._source = source
        self._transcriber = transcriber
        self._hook_finder = hook_finder
        self._renderer = renderer
        self._paths = paths.ensure()
        self._clip_count = max(clip_count, 1)
        self.tracker = ProgressTracker(progress)
        self._timings: list[StageTiming] = []

    def prepare(self, url: str) -> RunResult:
        """Run everything up to the point the user can edit.

        Rendering is deliberately not here. The user picks a clip and edits it
        first, and only then pays for an encode.
        """
        self._timings = []
        prune_input(self._paths.input_dir)
        slug = _slug(url)

        with self._stage("audio-fetch"):
            duration = self._source.probe_duration(url)
            audio = self._fetch_audio_once(url, slug, duration)

        with self._stage("survey"):
            transcript = self._survey_once(audio, slug, duration)

        with self._stage("hook"):
            selections = self._select_hooks(transcript)

        clips: list[Clip] = []
        videos: list[Path] = []

        with self._stage("precise"):
            for index, selection in enumerate(selections):
                with self.tracker.slice(index, len(selections)):
                    words = self._transcriber.precise(
                        audio, selection.start, selection.end
                    )
                clips.append(
                    Clip(
                        source_url=url,
                        start=selection.start,
                        end=selection.end,
                        words=words,
                        origin=selection.origin,
                        reason=selection.reason,
                        truncated=selection.truncated,
                        score=selection.score,
                        rank=selection.rank,
                    )
                )

        with self._stage("video-fetch"):
            for index, selection in enumerate(selections):
                with self.tracker.slice(index, len(selections)):
                    videos.append(
                        self._source.fetch_video_window(
                            url,
                            selection.start,
                            selection.end,
                            self._paths.input_dir / f"{slug}-clip{selection.rank}",
                        )
                    )

        clip_set = ClipSet(source_url=url, clips=clips)

        with self._stage("captions"):
            for clip in clips:
                self.write_caption_files(clip, f"{slug}-{clip.rank}")

        return RunResult(
            clip_set=clip_set, video_paths=videos, timings=list(self._timings)
        )

    def _fetch_audio_once(self, url: str, slug: str, duration: float) -> Path:
        """Reuse audio already in `input/` when it matches the source.

        Checked against the real duration rather than mere existence: a
        half-written file from an interrupted run exists too, and silently
        transcribing that would produce a transcript of the wrong episode.
        """
        candidate = self._paths.input_dir / f"{slug}-audio.wav"
        if candidate.exists():
            existing = _probe_duration(candidate)
            if existing is not None and abs(existing - duration) <= 1.0:
                self.tracker.update(100.0, "already downloaded")
                return candidate
        return self._source.fetch_audio(url, self._paths.input_dir / f"{slug}-audio")

    def _survey_once(self, audio: Path, slug: str, duration: float) -> Transcript:
        """Transcribe, or reuse a cached transcript for the same audio.

        The survey pass is two thirds of the wall clock and its result depends
        only on the audio file, so re-running it for the same episode is pure
        waste. The cache is keyed on the audio's size and mtime: a re-fetched
        or truncated file misses, rather than silently reusing a transcript of
        different audio.
        """
        cache_path = self._paths.work_dir / f"{slug}-transcript.json"
        stat = audio.stat()
        fingerprint = {"bytes": stat.st_size, "mtime": int(stat.st_mtime)}

        if cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                if cached.get("fingerprint") == fingerprint:
                    self.tracker.update(100.0, "reusing cached transcript")
                    return Transcript.model_validate(cached["transcript"])
            except (json.JSONDecodeError, KeyError, ValueError):
                # A corrupt cache is not a reason to fail the run; transcribe
                # again and overwrite it.
                pass

        transcript = self._transcriber.survey(audio)
        if transcript.source_duration <= 0:
            transcript = transcript.model_copy(update={"source_duration": duration})

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps({"fingerprint": fingerprint, "transcript": transcript.model_dump()}),
            encoding="utf-8",
        )
        return transcript

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

    def export(self, result: RunResult, clip_index: int, slug: str | None = None) -> Path:
        """Burn in and encode one clip.

        Split from `prepare` so an edit costs a caption rebuild, not a re-fetch.
        """
        clips = result.clip_set.ranked()
        if not 0 <= clip_index < len(clips):
            raise IndexError(f"no clip at index {clip_index}")

        clip = clips[clip_index]
        name = slug or f"{_slug(result.clip_set.source_url)}-{clip.rank}"
        ass_path, _ = self.write_caption_files(clip, name)
        destination = self._paths.output_dir / f"{name}.mp4"

        # The fetched window carries padding, so the burn-in cut is relative to
        # where that window actually began rather than to the episode.
        window_offset = max(clip.start - 2.0, 0.0)
        local_start = clip.start - window_offset
        local_end = local_start + clip.duration

        before = len(self._timings)
        with self._stage("render"):
            output = self._renderer.render(
                result.video_paths[clip_index], ass_path, local_start, local_end, destination
            )
        # The caller holds its own copy of the timings list, so the render row
        # has to be handed back explicitly or it never appears in the report.
        result.timings.extend(self._timings[before:])

        result.output_paths[clip_index] = output
        self._write_run_log(result.clip_set.source_url, output)
        return output

    def cleanup(self) -> None:
        """Clear intermediates, keeping the transcript cache.

        The cache is the most expensive thing on disk to rebuild, and it is
        small. Deleting it would make every re-run pay the survey pass again.
        """
        clear_work(self._paths.work_dir, keep_suffixes=("-transcript.json",))

    def _select_hooks(self, transcript: Transcript) -> list[HookSelection]:
        """Retry once, then the deterministic heuristic.

        Candidates are validated individually: one bad entry in the list costs
        that entry, not the whole generation. Only an empty survivor set falls
        back.
        """
        first_reason = ""
        try:
            candidates = self._hook_finder.find(transcript, self._clip_count)
            selections = self._validate_all(candidates.clips, transcript, "llm")
            if selections:
                return selections
            first_reason = "no candidate survived validation"
        except Exception as error:  # noqa: BLE001
            # Broad on purpose: an adapter can fail in ways the core cannot
            # enumerate (socket reset, model unloaded, malformed JSON), and
            # every one of them must reach the retry rather than the user.
            first_reason = str(error)

        self.tracker.update(50.0, f"retrying — {first_reason}")

        retry = getattr(self._hook_finder, "find_with_schema_restated", None)
        if retry is not None:
            try:
                candidates = retry(transcript, first_reason, self._clip_count)
                selections = self._validate_all(candidates.clips, transcript, "llm-retry")
                if selections:
                    return selections
            except Exception as error:  # noqa: BLE001 - same reasoning
                self.tracker.update(75.0, f"falling back to heuristic — {error}")

        return [
            self._snapped(selection, transcript)
            for selection in heuristic_hooks(transcript, self._clip_count)
        ]

    @staticmethod
    def _snapped(selection: HookSelection, transcript: Transcript) -> HookSelection:
        """Apply the same sentence snapping to a heuristic pick."""
        start, end = snap_to_sentences(selection.start, selection.end, transcript)
        if not is_well_formed(start, end):
            return selection
        return selection.model_copy(update={"start": start, "end": end})

    def _validate_all(self, candidates, transcript: Transcript, origin: str) -> list[HookSelection]:
        """Run the ladder over every candidate, keeping the survivors."""
        survivors: list[HookSelection] = []
        for candidate in candidates:
            try:
                outcome = validate_candidate(candidate, transcript)
            except HookRejected:
                continue  # one bad span does not cost the others
            # The model can only name boundaries that exist in the prompt it
            # was given, and that prompt is chunked. Snapping moves the span
            # onto sentence edges so a clip does not open or close mid-phrase.
            start, end = snap_to_sentences(outcome.start, outcome.end, transcript)
            if not is_well_formed(start, end):
                continue

            if conflicts_with(start, end, [(k.start, k.end) for k in survivors]):
                continue  # adjacent or overlapping clips are one moment, twice
            survivors.append(
                HookSelection(
                    start=start,
                    end=end,
                    reason=candidate.reason,
                    origin=origin,
                    truncated=outcome.truncated,
                    rank=len(survivors) + 1,
                )
            )
        return survivors

    @contextmanager
    def _stage(self, name: str):
        """Time a stage and drive the progress tracker across it."""
        self.tracker.begin(name)
        started = time.monotonic()
        try:
            yield
        finally:
            elapsed = time.monotonic() - started
            self._timings.append(StageTiming(stage=name, seconds=elapsed))
            self.tracker.finish(name)

    def _write_run_log(self, url: str, output: Path) -> None:
        """Append measured stage times. This is what replaces the estimates."""
        log_path = self._paths.work_dir / "run_log.jsonl"
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


def _probe_duration(media: Path) -> float | None:
    """Duration of a local file, or None when ffprobe cannot read it."""
    import subprocess

    try:
        result = subprocess.run(
            [
                resolve_executable("ffprobe"),
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=nw=1:nk=1",
                str(media),
            ],
            capture_output=True,
            text=True,
            check=True,
            shell=False,
        )
        return float(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        # An unreadable file is treated as absent, so the caller re-fetches.
        return None


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
