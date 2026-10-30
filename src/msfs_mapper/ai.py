"""Thin wrapper around the Claude API for the structured calls this project makes."""

from __future__ import annotations

import base64
import io
import mimetypes
from pathlib import Path
from typing import Any, TypeVar

import anthropic
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel

MODEL = "claude-opus-5-5"
# Server-side refusal fallback: a declined request is re-run on Anthropic's recommended
# fallback model inside the same call instead of failing.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
# The API downscales anything with a longer edge past this, so sending more only costs upload time.
MAX_IMAGE_EDGE = 1568

T = TypeVar("T", bound=BaseModel)


class AIError(RuntimeError):
    pass


def image_block(path: Path) -> dict[str, Any]:
    media_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    if media_type not in {"image/jpeg", "image/png", "image/gif", "image/webp"}:
        raise AIError(f"unsupported image type {media_type} for {path}")
    try:
        with Image.open(path) as image:
            # Phone photos are often stored sideways with an EXIF rotation tag; bake it in.
            image = ImageOps.exif_transpose(image).convert("RGB")
            image.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE), Image.Resampling.LANCZOS)
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=85)
    except (OSError, UnidentifiedImageError) as e:
        raise AIError(f"cannot read image {path}: {e}") from e
    data = base64.standard_b64encode(buffer.getvalue()).decode("ascii")
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}


class Claude:
    """Returns validated pydantic objects from Claude using structured outputs."""

    def __init__(
        self, client: anthropic.Anthropic | None = None, model: str = MODEL, api_key: str | None = None
    ):
        # A key saved in the app wins; otherwise the SDK finds ANTHROPIC_API_KEY or an `ant auth login`.
        self.client = client or (anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic())
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
        except TypeError as exc:
            # The SDK raises TypeError at request time when no credential source resolves.
            if "authentication" not in str(exc).lower():
                raise
            raise AIError(
                "no Claude credentials: enter a key with \"API key…\" in the window, "
                "set ANTHROPIC_API_KEY or run `ant auth login`, or turn AI off (--no-ai)"
            ) from exc
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
