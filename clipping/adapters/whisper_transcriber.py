"""Transcriber backed by faster-whisper (CTranslate2, int8 on CPU).

Two passes, deliberately asymmetric: a small model reads the whole hour to find
the hook, and a larger one reads only the chosen window with word timestamps on.
Buying word-level timing for the whole episode is the single largest cost in the
pipeline, and 3,540 of those seconds get thrown away.
"""

from __future__ import annotations

import os
from pathlib import Path

from clipping.config import PRECISE_MODEL, SURVEY_MODEL
from clipping.core.models import Segment, Transcript, Word


class TranscriptionError(RuntimeError):
    """The model could not be loaded or the audio could not be read."""


class FasterWhisperTranscriber:
    """Loads models lazily and caches them per size.

    Model load is seconds of CPU; the precise pass would otherwise pay it again
    for a 60-second window.
    """

    def __init__(
        self,
        survey_model: str = SURVEY_MODEL,
        precise_model: str = PRECISE_MODEL,
        compute_type: str = "int8",
        threads: int | None = None,
    ) -> None:
        self._survey_model_name = survey_model
        self._precise_model_name = precise_model
        self._compute_type = compute_type
        self._threads = threads or (os.cpu_count() or 4)
        self._loaded: dict[str, object] = {}

    def survey(self, audio: Path) -> Transcript:
        """Whole episode, segment level. Word timings are not required here."""
        model = self._model(self._survey_model_name)
        segments_iter, info = model.transcribe(  # type: ignore[attr-defined]
            str(audio),
            language="en",
            word_timestamps=False,
            vad_filter=True,
        )
        segments = [
            Segment(text=segment.text.strip(), start=segment.start, end=segment.end)
            for segment in segments_iter
            if segment.text.strip()
        ]
        if not segments:
            raise TranscriptionError(
                f"no speech found in {audio.name}; is the audio silent or non-English?"
            )
        return Transcript(
            segments=segments,
            language=info.language,
            source_duration=info.duration,
        )

    def precise(self, audio: Path, start: float, end: float) -> list[Word]:
        """One window, word level. Returned times are absolute in the episode.

        `clip_timestamps` keeps the returned times in the episode's own time
        base, so nothing downstream has to remember an offset.
        """
        model = self._model(self._precise_model_name)
        segments_iter, _ = model.transcribe(  # type: ignore[attr-defined]
            str(audio),
            language="en",
            word_timestamps=True,
            vad_filter=False,
            clip_timestamps=[start, end],
        )

        words: list[Word] = []
        for segment in segments_iter:
            for word in getattr(segment, "words", None) or []:
                text = word.word.strip()
                if not text:
                    continue
                words.append(Word(text=text, start=word.start, end=word.end))

        if not words:
            raise TranscriptionError(
                f"the precise pass found no words between {start:.1f}s and {end:.1f}s"
            )
        return words

    def _model(self, name: str):  # noqa: ANN202 - third-party type, not ours to name
        if name not in self._loaded:
            try:
                from faster_whisper import WhisperModel
            except ImportError as error:
                raise TranscriptionError(
                    "faster-whisper is not installed; run `pip install -r requirements.txt`"
                ) from error
            self._loaded[name] = WhisperModel(
                name,
                device="cpu",
                compute_type=self._compute_type,
                cpu_threads=self._threads,
            )
        return self._loaded[name]
