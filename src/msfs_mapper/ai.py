"""Thin wrapper around the Claude API for the structured calls this project makes."""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any, TypeVar

import anthropic
from pydantic import BaseModel

MODEL = "claude-opus-5-5"
# Server-side refusal fallback: a declined request is re-run on Anthropic's recommended
# fallback model inside the same call instead of failing.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

T = TypeVar("T", bound=BaseModel)


class AIError(RuntimeError):
    pass


def image_block(path: Path) -> dict[str, Any]:
    media_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    if media_type not in {"image/jpeg", "image/png", "image/gif", "image/webp"}:
        raise AIError(f"unsupported image type {media_type} for {path}")
    data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}


class Claude:
    """Returns validated pydantic objects from Claude using structured outputs."""

    def __init__(self, client: anthropic.Anthropic | None = None, model: str = MODEL):
        self.client = client or anthropic.Anthropic()
        self.model = model

    def structured(
        self,
        *,
        system: str,
        content: list[dict[str, Any]],
        output: type[T],
        effort: str = "high",
    ) -> T:
        try:
            response = self.client.beta.messages.parse(
                model=self.model,
                max_tokens=16000,
                system=system,
                messages=[{"role": "user", "content": content}],
                thinking={"type": "adaptive"},
                output_config={"effort": effort},
                output_format=output,
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
        except anthropic.APIConnectionError as exc:
            raise AIError(f"could not reach the Claude API: {exc}") from exc
        except anthropic.APIStatusError as exc:
            raise AIError(f"Claude API error {exc.status_code}: {exc.message}") from exc

        if response.stop_reason == "refusal":
            raise AIError("Claude declined this request")
        if response.stop_reason == "max_tokens":
            raise AIError("Claude response was truncated (max_tokens)")
        if response.parsed_output is None:
            raise AIError("Claude returned no structured output")
        return response.parsed_output
