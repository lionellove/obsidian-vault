"""Visual question answering through SiliconFlow's multimodal API."""

from __future__ import annotations

import base64
import mimetypes
import os
from pathlib import Path
from typing import Any

from openai import OpenAI
from PIL import Image
from smolagents import Tool


DEFAULT_API_BASE = "https://api.siliconflow.cn/v1"
DEFAULT_MODEL_ID = "Qwen/Qwen3-VL-32B-Instruct"
DEFAULT_DETAIL = "high"
DEFAULT_MAX_TOKENS = 1024
DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_MAX_IMAGE_BYTES = 20 * 1024 * 1024


class AnalyzeImageTool(Tool):
    """Keep GAIA's stable interface while delegating vision to SiliconFlow."""

    name = "analyze_image"
    description = (
        "Answer a focused question about an image with SiliconFlow's hosted "
        "vision-language model. Use it for image attachments, charts, "
        "diagrams, screenshots, maps, objects, or visible text. The result is "
        "machine-generated and consequential details should be cross-checked."
    )
    inputs = {
        "source": {
            "type": "string",
            "description": "Local image path or direct public HTTP/HTTPS image URL.",
        },
        "question": {
            "type": "string",
            "description": (
                "A specific question about the image. Ask for exact "
                "transcription when text or labels matter."
            ),
        },
    }
    output_type = "string"

    def __init__(self) -> None:
        super().__init__()
        self._client: OpenAI | None = None
        self._client_configuration: tuple[str, str, float] | None = None

    def forward(self, source: str, question: str) -> str:
        source = source.strip()
        question = question.strip()
        if not source:
            raise ValueError("source must not be empty")
        if not question:
            raise ValueError("question must not be empty")

        model_id = os.getenv("SILICON_VISION_MODEL", DEFAULT_MODEL_ID).strip()
        api_base = os.getenv("SILICON_BASE_URL", DEFAULT_API_BASE).strip()
        try:
            response = self._get_client().chat.completions.create(
                model=model_id,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": _image_url(source),
                                    "detail": _detail(),
                                },
                            },
                            {"type": "text", "text": question},
                        ],
                    }
                ],
                max_tokens=_max_tokens(),
                temperature=0.1,
            )
            text = _response_text(response)
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}".rstrip()
            raise RuntimeError(
                "SiliconFlow visual question answering failed "
                f"for model {model_id!r} at {api_base!r} ({detail}). "
                "Check SILICON_TOKEN, the selected SILICON_VISION_MODEL, "
                "the image source, account balance, and service availability."
            ) from exc

        if not text:
            raise RuntimeError("SiliconFlow visual model returned no text")
        return text

    def _get_client(self) -> OpenAI:
        token = (
            os.getenv("SILICON_TOKEN")
            or os.getenv("SILICONFLOW_API_KEY")
            or ""
        ).strip()
        if not token:
            raise RuntimeError(
                "SILICON_TOKEN is not configured "
                "(SILICONFLOW_API_KEY is also accepted)"
            )
        api_base = os.getenv("SILICON_BASE_URL", DEFAULT_API_BASE).strip()
        if not api_base:
            raise RuntimeError("SILICON_BASE_URL must not be empty")
        timeout = _timeout_seconds()
        configuration = (token, api_base, timeout)
        if self._client is None or self._client_configuration != configuration:
            self._client = OpenAI(
                api_key=token,
                base_url=api_base,
                timeout=timeout,
                max_retries=1,
            )
            self._client_configuration = configuration
        return self._client


def _image_url(source: str) -> str:
    lowered = source.lower()
    if lowered.startswith(("http://", "https://", "data:image/")):
        return source

    path = Path(source).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"Local image does not exist: {path}")
    size = path.stat().st_size
    max_size = _max_image_bytes()
    if size > max_size:
        raise ValueError(
            f"Local image size {size} bytes exceeds "
            f"SILICON_VISION_MAX_IMAGE_BYTES={max_size}"
        )

    mime_type, _ = mimetypes.guess_type(path.name)
    if not mime_type or not mime_type.startswith("image/"):
        with Image.open(path) as image:
            mime_type = image.get_format_mimetype()
        if not mime_type:
            raise ValueError(
                f"Cannot determine an image media type from local file: {path}"
            )
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _detail() -> str:
    detail = os.getenv("SILICON_VISION_DETAIL", DEFAULT_DETAIL).strip().lower()
    if detail not in {"low", "high", "auto"}:
        raise ValueError(
            "SILICON_VISION_DETAIL must be one of: low, high, auto"
        )
    return detail


def _max_tokens() -> int:
    raw_value = os.getenv(
        "SILICON_VISION_MAX_TOKENS",
        str(DEFAULT_MAX_TOKENS),
    )
    value = int(raw_value)
    if value < 1:
        raise ValueError("SILICON_VISION_MAX_TOKENS must be positive")
    return value


def _timeout_seconds() -> float:
    raw_value = os.getenv(
        "SILICON_VISION_TIMEOUT_SECONDS",
        str(DEFAULT_TIMEOUT_SECONDS),
    )
    value = float(raw_value)
    if value <= 0:
        raise ValueError("SILICON_VISION_TIMEOUT_SECONDS must be positive")
    return value


def _max_image_bytes() -> int:
    raw_value = os.getenv(
        "SILICON_VISION_MAX_IMAGE_BYTES",
        str(DEFAULT_MAX_IMAGE_BYTES),
    )
    value = int(raw_value)
    if value < 1:
        raise ValueError("SILICON_VISION_MAX_IMAGE_BYTES must be positive")
    return value


def _response_text(response: Any) -> str:
    choices = getattr(response, "choices", None)
    if not choices:
        raise RuntimeError("response contains no choices")
    content = getattr(choices[0].message, "content", None)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif isinstance(getattr(item, "text", None), str):
                parts.append(item.text)
        return "\n".join(parts).strip()
    return ""
