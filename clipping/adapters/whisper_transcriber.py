"""Transcriber backed by faster-whisper (CTranslate2, int8 on CPU).

Two passes, deliberately asymmetric: a small model reads the whole hour to find
hooks, and a larger one reads only the chosen windows with word timestamps on.
Buying word-level timing for the whole episode is the single largest cost in the
pipeline, and most of those seconds get thrown away.

Measured on 12 CPU cores: survey with `base` runs at ~14x realtime, the precise
pass with `medium` at ~1.9x.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from clipping.adapters.model_cache import ensure_downloaded
from clipping.config import PRECISE_MODEL, SURVEY_MODEL, TRANSCRIBE_LANGUAGE
from clipping.core.models import Segment, Transcript, Word

ProgressCallback = Callable[[float, str], None]


class TranscriptionError(RuntimeError):
    """The model could not be loaded or the audio could not be read."""


class LanguageMismatch(TranscriptionError):
    """The audio is not in the language the pipeline is configured for.

    This exists because the failure is otherwise silent and total. Told
    `language="en"`, Whisper does not refuse non-English audio — it produces
    fluent, well-punctuated English nonsense. Everything downstream then works
    perfectly on gibberish: the hooks are chosen from it, the captions are
    written from it, and the clips look fine and mean nothing.
    """


class FasterWhisperTranscriber:
    """Loads models lazily and caches them per size.

    Model load is seconds of CPU; the precise pass would otherwise pay it again
    for every window.
    """

    def __init__(
        self,
        survey_model: str = SURVEY_MODEL,
        precise_model: str = PRECISE_MODEL,
        compute_type: str = "int8",
        threads: int | None = None,
        language: str = TRANSCRIBE_LANGUAGE,
        on_progress: ProgressCallback | None = None,
        on_download: ProgressCallback | None = None,
    ) -> None:
        self._language = language
        self._survey_model_name = survey_model
        self._precise_model_name = precise_model
        self._compute_type = compute_type
        self._threads = threads or (os.cpu_count() or 4)
        self._on_progress = on_progress or (lambda percent, detail: None)
        self._on_download = on_download or (lambda percent, detail: None)
        self._loaded: dict[str, object] = {}

    def survey(self, audio: Path) -> Transcript:
        """Whole episode, segment level. Word timings are not required here.

        The generator is consumed one segment at a time so progress can be
        reported as decoding advances. This stage is roughly 45% of the run, so
        it is the one that most needs to visibly move.
        """
        model = self._model(self._survey_model_name)
        # language=None asks Whisper to detect rather than assume. Assuming is
        # what produced a fluent English transcript of Indonesian audio.
        segments_iter, info = model.transcribe(  # type: ignore[attr-defined]
            str(audio),
            language=None,
            word_timestamps=False,
            vad_filter=True,
        )

        detected = info.language
        if detected != self._language:
            raise LanguageMismatch(
                f"this audio is {detected} "
                f"({info.language_probability:.0%} confidence), but the pipeline "
                f"is configured for {self._language}.\n\n"
                f"Transcribing it as {self._language} does not fail loudly — it "
                f"produces fluent {self._language} nonsense, and every clip "
                "built from it is meaningless.\n\n"
                f"To process {detected} audio, set TRANSCRIBE_LANGUAGE = "
                f'"{detected}" in clipping/config.py. Note that PRD.md scopes '
                "the MVP to English, so caption quality for other languages is "
                "not yet verified."
            )

        total = info.duration or 0.0
        segments: list[Segment] = []
        for segment in segments_iter:
            text = segment.text.strip()
            if text:
                segments.append(Segment(text=text, start=segment.start, end=segment.end))
            if total > 0:
                self._on_progress(
                    min(segment.end / total * 100.0, 100.0),
                    f"{len(segments)} segments",
                )

        if not segments:
            raise TranscriptionError(
                f"no speech found in {audio.name}; is the audio silent or non-English?"
            )
        return Transcript(
            segments=segments,
            language=info.language,
            source_duration=total,
        )

    def precise(self, audio: Path, start: float, end: float) -> list[Word]:
        """One window, word level. Returned times are absolute in the episode.

        `clip_timestamps` keeps the returned times in the episode's own time
        base, so nothing downstream has to remember an offset.
        """
        model = self._model(self._precise_model_name)
        segments_iter, _ = model.transcribe(  # type: ignore[attr-defined]
            str(audio),
            language=self._language,
            word_timestamps=True,
            vad_filter=False,
            clip_timestamps=[start, end],
        )

        span = max(end - start, 0.001)
        words: list[Word] = []
        for segment in segments_iter:
            for word in getattr(segment, "words", None) or []:
                text = word.word.strip()
                if not text:
                    continue
                words.append(Word(text=text, start=word.start, end=word.end))
            self._on_progress(
                min((segment.end - start) / span * 100.0, 100.0),
                f"{len(words)} words",
            )

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

            # Downloading before constructing the model is what makes the wait
            # visible. WhisperModel would otherwise fetch silently.
            ensure_downloaded(name, self._on_download)

            self._loaded[name] = WhisperModel(
                name,
                device="cpu",
                compute_type=self._compute_type,
                cpu_threads=self._threads,
            )
        return self._loaded[name]
