"""Whisper model download, with a percentage.

The single worst moment in the product's history was a first run that spent
eleven minutes pulling 1.6 GB of models while printing nothing at all. The
pipeline was never slow; it was silent, and silence is indistinguishable from
a hang.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

REPO_TEMPLATE: Final = "Systran/faster-whisper-{size}"

# Approximate on-disk sizes, for telling the user what they are waiting for.
# Rough by design: "about 1.5 GB" is the useful fact, not the exact byte count.
APPROXIMATE_SIZE: Final[dict[str, str]] = {
    "tiny": "~75 MB",
    "base": "~140 MB",
    "small": "~480 MB",
    "medium": "~1.5 GB",
    "large-v2": "~3 GB",
    "large-v3": "~3 GB",
}


class ModelDownloadError(RuntimeError):
    """The model could not be fetched."""


def is_cached(size: str) -> bool:
    """True when the model is already on disk and needs no download.

    Checks for the model weights specifically. A cache directory can exist
    holding only a lock file or a partial fetch, so directory presence alone
    would wrongly promise the run is about to start.
    """
    try:
        from huggingface_hub import try_to_load_from_cache
    except ImportError:  # huggingface_hub ships with faster-whisper
        return False

    repo = REPO_TEMPLATE.format(size=size)
    for filename in ("model.bin", "config.json"):
        result = try_to_load_from_cache(repo_id=repo, filename=filename)
        if not isinstance(result, str):
            return False
    return True


def ensure_downloaded(
    size: str, on_progress: Callable[[float, str], None] | None = None
) -> None:
    """Download the model if it is missing, reporting real percentages.

    `snapshot_download` drives a tqdm instance per file; substituting our own
    class is the supported way to observe it without scraping stderr.
    """
    if is_cached(size):
        return

    report = on_progress or (lambda percent, detail: None)
    repo = REPO_TEMPLATE.format(size=size)
    approximate = APPROXIMATE_SIZE.get(size, "size unknown")
    report(0.0, f"{size} model, {approximate}, one time only")

    try:
        from huggingface_hub import snapshot_download
        from tqdm.auto import tqdm as base_tqdm
    except ImportError as error:
        raise ModelDownloadError(
            "huggingface_hub is required to fetch Whisper models"
        ) from error

    class ReportingTqdm(base_tqdm):  # type: ignore[misc]
        """A tqdm that forwards its counter into the progress tracker.

        Files are downloaded one at a time, so the largest file dominates and
        reporting the current file's own percentage tracks reality closely
        enough to be honest.
        """

        def update(self, n: int | float | None = 1) -> bool | None:
            result = super().update(n)
            total = getattr(self, "total", None)
            if total:
                percent = min(self.n / total * 100.0, 100.0)
                report(percent, f"{size} model, {approximate}, one time only")
            return result

    try:
        snapshot_download(repo_id=repo, tqdm_class=ReportingTqdm)
    except Exception as error:  # noqa: BLE001
        # Broad because hub failures arrive as several unrelated types
        # (network, auth, disk); every one of them means the same thing here
        # and the message carries the detail.
        raise ModelDownloadError(
            f"could not download the {size} Whisper model: {error}"
        ) from error

    report(100.0, f"{size} model ready")
