"""Disk retention.

`work/` is cleared after a successful run. `input/` is capped by age and total
size, oldest first. `output/` is never touched — it holds the user's finished
work, and deleting that would be the worst bug this project could ship.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from clipping.config import INPUT_MAX_AGE_DAYS, INPUT_MAX_BYTES


def clear_work(work_dir: Path) -> None:
    """Remove intermediates after a successful run."""
    if not work_dir.exists():
        return
    for entry in work_dir.iterdir():
        if entry.is_dir():
            shutil.rmtree(entry, ignore_errors=True)
        else:
            entry.unlink(missing_ok=True)


def prune_input(
    input_dir: Path,
    max_age_days: int = INPUT_MAX_AGE_DAYS,
    max_bytes: int = INPUT_MAX_BYTES,
) -> list[Path]:
    """Delete old or excess fetched media, oldest first. Returns what went.

    Run at startup. Without it, hour-long downloads accumulate until the disk
    fills.
    """
    if not input_dir.exists():
        return []

    files = sorted(
        (entry for entry in input_dir.iterdir() if entry.is_file()),
        key=lambda entry: entry.stat().st_mtime,
    )
    removed: list[Path] = []
    cutoff = time.time() - max_age_days * 86400

    for entry in list(files):
        if entry.stat().st_mtime < cutoff:
            entry.unlink(missing_ok=True)
            removed.append(entry)
            files.remove(entry)

    total = sum(entry.stat().st_size for entry in files)
    for entry in list(files):
        if total <= max_bytes:
            break
        total -= entry.stat().st_size
        entry.unlink(missing_ok=True)
        removed.append(entry)
        files.remove(entry)

    return removed
