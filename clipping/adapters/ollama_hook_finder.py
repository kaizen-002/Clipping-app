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
Each segment must come from a DIFFERENT part of the episode. Never return the
same span twice with different wording — that is one clip, not several.

Reply with one JSON object and nothing else. No prose, no code fence:
{"clips": [{"start_seconds": <number>, "end_seconds": <number>, "reason": "<one sentence>"}]}

Every timestamp must be a second that appears in the transcript below."""


def _response_schema(count: int) -> dict[str, Any]:
    """The exact shape the model may emit, bounded to `count` clips.

    The bound is not cosmetic. With an unbounded array the model kept
    generating and a 30-minute episode took over ten minutes; with maxItems it
    takes about ten seconds. Measured, both ways.
    """
    return {
        "type": "object",
        "properties": {
            "clips": {
                "type": "array",
                "minItems": 1,
                "maxItems": count,
                "items": {
                    "type": "object",
                    "properties": {
                        "start_seconds": {"type": "number"},
                        "end_seconds": {"type": "number"},
                        "reason": {"type": "string"},
                    },
                    "required": ["start_seconds", "end_seconds", "reason"],
                },
            }
        },
        "required": ["clips"],
    }


# Enough for a handful of clips and their one-sentence reasons. A cap here is
# a second line of defence behind maxItems.
_MAX_TOKENS = 500


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
        return self._ask(self._render_prompt(transcript, count), count)

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
        return self._ask(prompt, count)

    def _render_prompt(self, transcript: Transcript, count: int = 3) -> str:
        # Merged, not raw: the full segment list is long enough that the model
        # stops obeying the schema. See Transcript.merged.
        lines = [
            f"[{segment.start:.1f} - {segment.end:.1f}] {segment.text}"
            for segment in transcript.merged().segments
        ]
        return (
            f"Return the top {count} segments, best first.\n"
            f"Episode duration: {transcript.source_duration:.1f} seconds.\n\n"
            "Transcript:\n" + "\n".join(lines)
        )

    def _ask(self, prompt: str, count: int) -> HookCandidateList:
        payload = {
            "model": self._model,
            "system": _SYSTEM_PROMPT,
            "prompt": prompt,
            "stream": False,
            # A JSON *schema*, not merely "json": this constrains decoding to
            # the exact shape. Asked for plain "json" on this prompt the model
            # returned `{}`; asked for free-form JSON it echoed prompt
            # fragments back as keys.
            "format": _response_schema(count),
            "options": {
                "temperature": 0.2,
                "num_predict": _MAX_TOKENS,
                # CPU only. A 14B model asked to use the GPU dies with
                # "Failed to allocate pinned memory" on this hardware, and
                # PRD.md's reference machine has no GPU at all.
                "num_gpu": 0,
            },
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
