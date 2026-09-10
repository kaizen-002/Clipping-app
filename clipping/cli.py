"""Terminal entry point.

The CLI exists before the UI on purpose: the performance target is a
commitment, and this is what turns it into measurements without anyone styling
a button first.
"""

from __future__ import annotations

import argparse
import sys

from clipping.adapters.ffmpeg_renderer import FfmpegRenderer, RenderError
from clipping.adapters.ollama_hook_finder import HookFinderError, OllamaHookFinder
from clipping.adapters.whisper_transcriber import (
    FasterWhisperTranscriber,
    TranscriptionError,
)
from clipping.adapters.ytdlp_source import MediaFetchError, YtDlpSource
from clipping.config import DEFAULT_PATHS
from clipping.core.hooks import HookRejected
from clipping.core.progress import ProgressEvent, ProgressSink, ProgressTracker
from clipping.pipeline import DEFAULT_CLIP_COUNT, Pipeline


def build_pipeline(
    progress: ProgressSink | None = None, clip_count: int = DEFAULT_CLIP_COUNT
) -> Pipeline:
    """Wire the concrete adapters. This is the composition root.

    The tracker is built here rather than inside Pipeline because the adapters
    need to report into the same one: progress from yt-dlp and Whisper has to
    land on the same bar as the stage transitions.
    """
    tracker = ProgressTracker(progress)

    def stage_progress(percent: float, detail: str) -> None:
        tracker.update(percent, detail)

    def download_progress(percent: float, detail: str) -> None:
        # Model downloads are their own stage: they are a one-time cost that
        # has nothing to do with this episode, and folding them into
        # "transcribing" is what made the first run look like a hang.
        tracker.begin("model-download", detail)
        tracker.update(percent, detail, determinate=percent > 0)

    pipeline = Pipeline(
        source=YtDlpSource(on_progress=stage_progress),
        transcriber=FasterWhisperTranscriber(
            on_progress=stage_progress, on_download=download_progress
        ),
        hook_finder=OllamaHookFinder(),
        renderer=FfmpegRenderer(on_progress=stage_progress),
        paths=DEFAULT_PATHS,
        progress=progress,
        clip_count=clip_count,
    )
    pipeline.tracker = tracker
    return pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="clipping",
        description="Turn a podcast episode into captioned vertical shorts.",
    )
    parser.add_argument("url", help="YouTube URL of the episode")
    parser.add_argument(
        "--clips", type=int, default=DEFAULT_CLIP_COUNT, help="how many clips to find"
    )
    parser.add_argument(
        "--no-export", action="store_true", help="stop before the encode"
    )
    args = parser.parse_args(argv)

    # The Windows console defaults to cp1252, which cannot encode a curly
    # quote or a dash. Clip reasons come from a language model and transcript
    # text comes from arbitrary speech, so a crash here is a matter of time.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")

    last_line = ""

    def show(event: ProgressEvent) -> None:
        nonlocal last_line
        bar_width = 24
        filled = int(event.overall_percent / 100 * bar_width)
        bar = "#" * filled + "." * (bar_width - filled)
        detail = f"  {event.detail}" if event.detail else ""
        line = f"\r[{bar}] {event.overall_percent:5.1f}%  {event.label}{detail}"
        # Pad to overwrite the previous, longer line rather than leaving its tail.
        sys.stdout.write(line.ljust(len(last_line)))
        sys.stdout.flush()
        last_line = line

    pipeline = build_pipeline(progress=show, clip_count=args.clips)

    try:
        result = pipeline.prepare(args.url)
    except (MediaFetchError, TranscriptionError, HookFinderError, HookRejected) as error:
        print(f"\n\nFailed: {error}", file=sys.stderr)
        return 1

    clips = result.clip_set.ranked()
    print(f"\n\nFound {len(clips)} clip(s):")
    for index, clip in enumerate(clips):
        marker = " (heuristic)" if clip.origin == "heuristic" else ""
        # Score only means something for heuristic picks; the model does not
        # produce one, and printing "score 0.00" next to a model pick reads as
        # a bad clip rather than an absent metric.
        scored = f", score {clip.score:.2f}" if clip.score else ""
        # ASCII hyphen: the Windows console is cp1252 and renders an en dash
        # as a replacement character.
        print(
            f"  {clip.rank}. {clip.start:7.1f}s - {clip.end:7.1f}s "
            f"({clip.duration:4.1f}s{scored}){marker}"
        )
        print(f"     {clip.reason}")

    if not args.no_export:
        try:
            output = pipeline.export(result, clip_index=0)
        except RenderError as error:
            print(f"\nRender failed: {error}", file=sys.stderr)
            return 1
        print(f"\nWrote {output}")

    print("\nMeasured stage times:")
    for timing in result.timings:
        print(f"  {timing.stage:<16} {timing.seconds:7.1f}s")
    print(f"  {'TOTAL':<16} {result.total_seconds:7.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
