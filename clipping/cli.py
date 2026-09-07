"""Terminal entry point.

The CLI exists before the UI on purpose: the 12-minute target is a commitment
backed only by estimates, and this is what turns it into measurements without
anyone styling a button first.
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
from clipping.pipeline import Pipeline


def build_pipeline(verbose: bool = True) -> Pipeline:
    """Wire the concrete adapters. This is the composition root."""

    def announce(stage: str, detail: str) -> None:
        if not verbose:
            return
        suffix = f" — {detail}" if detail else ""
        print(f"  {stage}{suffix}", flush=True)

    return Pipeline(
        source=YtDlpSource(),
        transcriber=FasterWhisperTranscriber(),
        hook_finder=OllamaHookFinder(),
        renderer=FfmpegRenderer(),
        paths=DEFAULT_PATHS,
        progress=announce,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="clipping",
        description="Turn a podcast episode into a captioned vertical short.",
    )
    parser.add_argument("url", help="YouTube URL of the episode")
    parser.add_argument(
        "--no-export",
        action="store_true",
        help="stop after caption generation, before the encode",
    )
    args = parser.parse_args(argv)

    pipeline = build_pipeline()

    try:
        result = pipeline.prepare(args.url)
    except (MediaFetchError, TranscriptionError, HookFinderError, HookRejected) as error:
        print(f"\nFailed: {error}", file=sys.stderr)
        return 1

    clip = result.clip
    print(f"\nHook: {clip.start:.1f}s – {clip.end:.1f}s ({clip.duration:.1f}s)")
    print(f"Chosen by: {clip.origin}")
    if clip.truncated:
        print("Note: the model's span exceeded 60s and was truncated.")
    print(f"Reason: {clip.reason}")
    print(f"Words: {len(clip.words)}")

    if not args.no_export:
        try:
            result = pipeline.export(result)
        except RenderError as error:
            print(f"\nRender failed: {error}", file=sys.stderr)
            return 1
        print(f"\nWrote {result.output_path}")
        print(f"Sidecar {result.srt_path}")

    print("\nMeasured stage times:")
    for timing in result.timings:
        print(f"  {timing.stage:<28} {timing.seconds:7.1f}s")
    print(f"  {'TOTAL':<28} {result.total_seconds:7.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
