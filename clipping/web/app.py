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
from clipping.core.editing import EditRejected, adjust_bounds, retime_words
from clipping.core.captions import group_into_lines
from clipping.core.models import Clip, Word
from clipping.pipeline import Pipeline, RunResult, _slug

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Podcast Shorts Generator", docs_url=None, redoc_url=None)


class _Run:
    """The single in-flight run, plus the progress the page polls for."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.result: RunResult | None = None
        self.stage: str = "idle"
        self.detail: str = ""
        self.error: str | None = None
        self.busy: bool = False
        self.pipeline: Pipeline | None = None


_run = _Run()


class PrepareRequest(BaseModel):
    url: str


class BoundsRequest(BaseModel):
    start: float
    end: float


class CaptionEdit(BaseModel):
    line_index: int
    text: str


def _progress(stage: str, detail: str) -> None:
    _run.stage = stage
    _run.detail = detail


def _clip_payload(clip: Clip) -> dict[str, Any]:
    """What the page needs to draw the timeline and the caption editor."""
    lines = group_into_lines(clip.words)
    return {
        "start": clip.start,
        "end": clip.end,
        "duration": clip.duration,
        "origin": clip.origin,
        "reason": clip.reason,
        "truncated": clip.truncated,
        "words": [w.model_dump() for w in clip.words],
        "lines": [
            {"index": index, "text": line.text, "start": line.start, "end": line.end}
            for index, line in enumerate(lines)
        ],
    }


@app.post("/api/prepare")
def prepare(request: PrepareRequest) -> dict[str, str]:
    """Kick off stages 1-6 on a worker thread.

    The work is minutes long, so it cannot run inside the request. The page
    polls /api/status.
    """
    if _run.busy:
        raise HTTPException(status_code=409, detail="a run is already in progress")

    _run.busy = True
    _run.error = None
    _run.result = None
    _run.stage = "starting"
    _run.detail = ""

    def worker() -> None:
        try:
            pipeline = build_pipeline(verbose=False)
            pipeline._progress = _progress  # noqa: SLF001 - composition root wiring
            _run.pipeline = pipeline
            _run.result = pipeline.prepare(request.url)
            _run.stage = "ready"
        except Exception as error:  # noqa: BLE001
            # Broad because this is the thread boundary: anything escaping here
            # would vanish into a dead thread and leave the page spinning
            # forever. The message is surfaced verbatim instead.
            _run.error = str(error)
            _run.stage = "failed"
        finally:
            _run.busy = False

    threading.Thread(target=worker, daemon=True).start()
    return {"status": "started"}


@app.get("/api/status")
def status() -> dict[str, Any]:
    """Stage name and detail, for the polite live region on the page."""
    payload: dict[str, Any] = {
        "stage": _run.stage,
        "detail": _run.detail,
        "busy": _run.busy,
        "error": _run.error,
    }
    if _run.result is not None:
        payload["clip"] = _clip_payload(_run.result.clip)
        payload["timings"] = [t.model_dump() for t in _run.result.timings]
        payload["exported"] = (
            str(_run.result.output_path) if _run.result.output_path else None
        )
    return payload


@app.post("/api/bounds")
def set_bounds(request: BoundsRequest) -> dict[str, Any]:
    """Move the clip's start/end. Invariants live in the domain, not here."""
    result = _require_result()
    try:
        updated = adjust_bounds(result.clip, request.start, request.end)
    except EditRejected as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    _run.result = RunResult(
        clip=updated,
        video_path=result.video_path,
        ass_path=result.ass_path,
        srt_path=result.srt_path,
        output_path=None,
        timings=result.timings,
    )
    return {"clip": _clip_payload(updated)}


@app.post("/api/caption")
def edit_caption(request: CaptionEdit) -> dict[str, Any]:
    """Edit one caption line's text, preserving the measured word timings."""
    result = _require_result()
    clip = result.clip
    lines = group_into_lines(clip.words)

    if not 0 <= request.line_index < len(lines):
        raise HTTPException(status_code=404, detail="no such caption line")

    target = lines[request.line_index]
    edited_tokens = request.text.split()

    try:
        retimed = retime_words(target.words, edited_tokens)
    except EditRejected as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    rebuilt: list[Word] = []
    for index, line in enumerate(lines):
        rebuilt.extend(retimed if index == request.line_index else line.words)

    updated = clip.model_copy(update={"words": rebuilt})
    _run.result = RunResult(
        clip=updated,
        video_path=result.video_path,
        ass_path=result.ass_path,
        srt_path=result.srt_path,
        output_path=None,
        timings=result.timings,
    )
    return {"clip": _clip_payload(updated)}


@app.post("/api/export")
def export() -> dict[str, Any]:
    """Stage 7: burn in and encode the edited clip."""
    result = _require_result()
    if _run.pipeline is None:
        raise HTTPException(status_code=409, detail="no pipeline for this run")
    if _run.busy:
        raise HTTPException(status_code=409, detail="a run is already in progress")

    _run.busy = True

    def worker() -> None:
        try:
            _run.stage = "7. Render"
            _run.result = _run.pipeline.export(result, _slug(result.clip.source_url))
            _run.stage = "exported"
        except Exception as error:  # noqa: BLE001 - thread boundary, see /api/prepare
            _run.error = str(error)
            _run.stage = "failed"
        finally:
            _run.busy = False

    threading.Thread(target=worker, daemon=True).start()
    return {"status": "started"}


@app.get("/api/video")
def video() -> FileResponse:
    """Serve the fetched window so the page can preview it."""
    result = _require_result()
    return FileResponse(result.video_path, media_type="video/mp4")


def _require_result() -> RunResult:
    if _run.result is None:
        raise HTTPException(status_code=409, detail="no clip is ready yet")
    return _run.result


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Run the local server. Never binds to 0.0.0.0."""
    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    serve()
