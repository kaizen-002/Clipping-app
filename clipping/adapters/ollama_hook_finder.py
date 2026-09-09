"""HookFinder backed by a local Llama 3 via Ollama.

The model is asked for JSON and nothing else, and the answer is still run
through the validation ladder in `core.hooks`. A model that is told to return
JSON is not the same as a model that did.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from pydantic import ValidationError

from clipping.config import OLLAMA_HOST, OLLAMA_MODEL
from clipping.core.models import HookCandidateList, Transcript


class HookFinderError(RuntimeError):
    """Ollama was unreachable, or its response was not usable."""


_SYSTEM_PROMPT = """You find the most engaging 15-60 second segments of a \
podcast transcript — the parts that would stop someone scrolling.

Prefer: a surprising claim, a strong opinion, a story turn, a question that lands.
Avoid: introductions, sponsor reads, sign-offs, and small talk.
The segments must not overlap each other, and are ordered best first.

Reply with one JSON object and nothing else. No prose, no code fence:
{"clips": [{"start_seconds": <number>, "end_seconds": <number>, "reason": "<one sentence>"}]}

Every timestamp must be a second that appears in the transcript below."""


class OllamaHookFinder:
    """Asks a local Llama 3 for a hook, twice at most."""

    def __init__(
        self,
        host: str = OLLAMA_HOST,
        model: str = OLLAMA_MODEL,
        timeout: float = 600.0,
    ) -> None:
        self._host = host.rstrip("/")
        self._model = model
        self._timeout = timeout

    def find(self, transcript: Transcript, count: int = 3) -> HookCandidateList:
        """One attempt. The retry lives in the pipeline, which owns the ladder."""
        return self._ask(self._render_prompt(transcript, count))

    def find_with_schema_restated(
        self, transcript: Transcript, failure: str, count: int = 3
    ) -> HookCandidateList:
        """The retry attempt, told exactly how the first one failed.

        Restating the schema alone tends to reproduce the same error; naming the
        specific rung that rejected the answer is what makes the retry useful.
        """
        prompt = (
            f"{self._render_prompt(transcript, count)}\n\n"
            f"Your previous answer was rejected: {failure}\n"
            "Return one JSON object only, obeying every constraint above."
        )
        return self._ask(prompt)

    def _render_prompt(self, transcript: Transcript, count: int = 3) -> str:
        lines = [
            f"[{segment.start:.1f} - {segment.end:.1f}] {segment.text}"
            for segment in transcript.segments
        ]
        return (
            f"Return the top {count} segments, best first.\n"
            f"Episode duration: {transcript.source_duration:.1f} seconds.\n\n"
            "Transcript:\n" + "\n".join(lines)
        )

    def _ask(self, prompt: str) -> HookCandidateList:
        payload = {
            "model": self._model,
            "system": _SYSTEM_PROMPT,
            "prompt": prompt,
            "stream": False,
            "format": "json",  # Ollama constrains decoding to valid JSON
            "options": {"temperature": 0.2},
        }
        try:
            response = httpx.post(
                f"{self._host}/api/generate", json=payload, timeout=self._timeout
            )
            response.raise_for_status()
        except httpx.ConnectError as error:
            raise HookFinderError(
                f"cannot reach Ollama at {self._host} — is `ollama serve` running?"
            ) from error
        except httpx.HTTPStatusError as error:
            raise HookFinderError(
                f"Ollama returned {error.response.status_code}: {error.response.text[:200]}"
            ) from error
        except httpx.TimeoutException as error:
            raise HookFinderError(
                f"Ollama did not answer within {self._timeout:.0f}s"
            ) from error

        return self._parse(response.json())

    def _parse(self, body: dict[str, Any]) -> HookCandidateList:
        raw = body.get("response", "")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as error:
            raise HookFinderError(
                f"model did not return JSON: {raw[:200]!r}"
            ) from error

        try:
            return HookCandidateList.model_validate(parsed)
        except ValidationError as error:
            raise HookFinderError(
                f"model JSON does not match the HookCandidateList contract: {error}"
            ) from error
