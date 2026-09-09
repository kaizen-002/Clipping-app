"""FastAPI serving one static page.

Bound to 127.0.0.1 — not reachable off the machine. No auth, because there is
no second user.

The server holds one run at a time. PRD.md puts batch processing out of scope,
so a dict of sessions would be speculative generality.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from clipping.cli import build_pipeline
from clipping.core.captions import group_into_lines
from clipping.core.editing import EditRejected, adjust_bounds, retime_words
from clipping.core.models import Clip, Word
from clipping.core.progress import ProgressEvent
from clipping.pipeline import DEFAULT_CLIP_COUNT, Pipeline, RunResult

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Podcast Shorts Generator", docs_url=None, redoc_url=None)


class _Run:
    """The single in-flight run, plus the progress the page polls for."""

    def __init__(self) -> None:
        self.result: RunResult | None = None
        self.event: ProgressEvent | None = None
        self.phase: str = "idle"  # idle | working | ready | exported | failed
        self.error: str | None = None
        self.busy: bool = False
        self.pipeline: Pipeline | None = None


_run = _Run()


class PrepareRequest(BaseModel):
    url: str
    clips: int = DEFAULT_CLIP_COUNT


class BoundsRequest(BaseModel):
    clip_index: int
    start: float
    end: float


class CaptionEdit(BaseModel):
    clip_index: int
    line_index: int
    text: str


class ExportRequest(BaseModel):
    clip_index: int


def _record(event: ProgressEvent) -> None:
    _run.event = event


def _clip_payload(clip: Clip, index: int) -> dict[str, Any]:
    """What the page needs to draw a card, the timeline and the caption editor."""
    lines = group_into_lines(clip.words)
    return {
        "index": index,
        "rank": clip.rank,
        "score": clip.score,
        "start": clip.start,
        "end": clip.end,
        "duration": clip.duration,
        "origin": clip.origin,
        "reason": clip.reason,
        "truncated": clip.truncated,
        "words": [word.model_dump() for word in clip.words],
        "lines": [
            {"index": i, "text": line.text, "start": line.start, "end": line.end}
            for i, line in enumerate(lines)
        ],
    }


def _all_clips() -> list[dict[str, Any]]:
    result = _require_result()
    return [
        _clip_payload(clip, index)
        for index, clip in enumerate(result.clip_set.ranked())
    ]


@app.post("/api/prepare")
def prepare(request: PrepareRequest) -> dict[str, str]:
    """Kick off the run on a worker thread.

    The work is minutes long, so it cannot run inside the request. The page
    polls /api/status.
    """
    if _run.busy:
        raise HTTPException(status_code=409, detail="a run is already in progress")

    _run.busy = True
    _run.error = None
    _run.result = None
    _run.event = None
    _run.phase = "working"

    def worker() -> None:
        try:
            pipeline = build_pipeline(progress=_record, clip_count=request.clips)
            _run.pipeline = pipeline
            _run.result = pipeline.prepare(request.url)
            _run.phase = "ready"
        except Exception as error:  # noqa: BLE001
            # Broad because this is the thread boundary: anything escaping here
            # would vanish into a dead thread and leave the page spinning
            # forever. The message is surfaced verbatim instead.
            _run.error = str(error)
            _run.phase = "failed"
        finally:
            _run.busy = False

    threading.Thread(target=worker, daemon=True).start()
    return {"status": "started"}


@app.get("/api/status")
def status() -> dict[str, Any]:
    """Progress and, once ready, the ranked clips."""
    event = _run.event
    payload: dict[str, Any] = {
        "phase": _run.phase,
        "busy": _run.busy,
        "error": _run.error,
        "label": event.label if event else "",
        "detail": event.detail if event else "",
        "stage": event.stage if event else "",
        "stage_percent": event.stage_percent if event else 0.0,
        "overall_percent": event.overall_percent if event else 0.0,
        "determinate": event.determinate if event else True,
    }
    if _run.result is not None:
        payload["clips"] = _all_clips()
        payload["timings"] = [t.model_dump() for t in _run.result.timings]
        payload["exports"] = {
            str(index): str(path)
            for index, path in _run.result.output_paths.items()
        }
    return payload


@app.post("/api/bounds")
def set_bounds(request: BoundsRequest) -> dict[str, Any]:
    """Move a clip's start/end. Invariants live in the domain, not here."""
    result = _require_result()
    clips = result.clip_set.ranked()
    clip = _require_clip(clips, request.clip_index)

    try:
        updated = adjust_bounds(clip, request.start, request.end)
    except EditRejected as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    clips[request.clip_index] = updated
    result.clip_set.clips = clips
    return {"clip": _clip_payload(updated, request.clip_index)}


@app.post("/api/caption")
def edit_caption(request: CaptionEdit) -> dict[str, Any]:
    """Edit one caption line's text, preserving the measured word timings."""
    result = _require_result()
    clips = result.clip_set.ranked()
    clip = _require_clip(clips, request.clip_index)
    lines = group_into_lines(clip.words)

    if not 0 <= request.line_index < len(lines):
        raise HTTPException(status_code=404, detail="no such caption line")

    try:
        retimed = retime_words(lines[request.line_index].words, request.text.split())
    except EditRejected as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    rebuilt: list[Word] = []
    for index, line in enumerate(lines):
        rebuilt.extend(retimed if index == request.line_index else line.words)

    updated = clip.model_copy(update={"words": rebuilt})
    clips[request.clip_index] = updated
    result.clip_set.clips = clips
    return {"clip": _clip_payload(updated, request.clip_index)}


@app.post("/api/export")
def export(request: ExportRequest) -> dict[str, str]:
    """Burn in and encode one clip."""
    result = _require_result()
    if _run.pipeline is None:
        raise HTTPException(status_code=409, detail="no pipeline for this run")
    if _run.busy:
        raise HTTPException(status_code=409, detail="a run is already in progress")

    _run.busy = True
    _run.phase = "working"
    pipeline = _run.pipeline

    def worker() -> None:
        try:
            pipeline.export(result, clip_index=request.clip_index)
            _run.phase = "exported"
        except Exception as error:  # noqa: BLE001 - thread boundary, see /api/prepare
            _run.error = str(error)
            _run.phase = "failed"
        finally:
            _run.busy = False

    threading.Thread(target=worker, daemon=True).start()
    return {"status": "started"}


@app.get("/api/video/{clip_index}")
def video(clip_index: int) -> FileResponse:
    """Serve a fetched window so the page can preview it."""
    result = _require_result()
    if not 0 <= clip_index < len(result.video_paths):
        raise HTTPException(status_code=404, detail="no such clip")
    return FileResponse(result.video_paths[clip_index], media_type="video/mp4")


def _require_result() -> RunResult:
    if _run.result is None:
        raise HTTPException(status_code=409, detail="no clips are ready yet")
    return _run.result


def _require_clip(clips: list[Clip], index: int) -> Clip:
    if not 0 <= index < len(clips):
        raise HTTPException(status_code=404, detail="no such clip")
    return clips[index]


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Run the local server. Never binds to 0.0.0.0.

    The banner is printed here rather than left to uvicorn's own logger: at
    log_level "warning" uvicorn says nothing at all, and a server that starts
    silently is indistinguishable from one that hung.
    """
    import uvicorn

    print(f"Serving on http://{host}:{port}  (Ctrl+C to stop)", flush=True)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    serve()
