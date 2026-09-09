"""Disk retention.

`output/` is never touched by any of this — it holds the user's finished work,
and deleting that would be the worst bug this project could ship.
"""

from __future__ import annotations

import time
from pathlib import Path

from clipping.retention import clear_work, prune_input


def write(path: Path, size: int = 16, age_days: float = 0.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    if age_days:
        when = time.time() - age_days * 86400
        import os

        os.utime(path, (when, when))
    return path


def test_clear_work_removes_intermediates(tmp_path: Path) -> None:
    work = tmp_path / "work"
    write(work / "clip.ass")
    write(work / "scratch.txt")
    clear_work(work)
    assert list(work.iterdir()) == []


def test_clear_work_keeps_the_transcript_cache(tmp_path: Path) -> None:
    """The survey pass is two thirds of a run; deleting its cache means
    re-running it for the same episode every time."""
    work = tmp_path / "work"
    write(work / "clip.ass")
    kept = write(work / "episode-transcript.json")
    clear_work(work, keep_suffixes=("-transcript.json",))
    assert [entry.name for entry in work.iterdir()] == [kept.name]


def test_prune_input_deletes_media_past_the_age_limit(tmp_path: Path) -> None:
    inputs = tmp_path / "input"
    old = write(inputs / "old.wav", age_days=30)
    fresh = write(inputs / "fresh.wav")
    removed = prune_input(inputs, max_age_days=7, max_bytes=10**9)
    assert removed == [old]
    assert fresh.exists()


def test_prune_input_enforces_the_size_cap_oldest_first(tmp_path: Path) -> None:
    inputs = tmp_path / "input"
    oldest = write(inputs / "a.wav", size=100, age_days=3)
    middle = write(inputs / "b.wav", size=100, age_days=2)
    newest = write(inputs / "c.wav", size=100, age_days=1)

    prune_input(inputs, max_age_days=365, max_bytes=250)

    assert not oldest.exists()
    assert middle.exists() and newest.exists()


def test_prune_input_on_a_missing_directory_is_not_an_error(tmp_path: Path) -> None:
    assert prune_input(tmp_path / "nope") == []
