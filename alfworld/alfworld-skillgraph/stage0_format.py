"""Deterministic JSON response normalization and format-only repair."""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from stage0_core import canonical, sha256


class FormatValidationError(ValueError):
    """Raised when a response is not a single safe JSON object."""


def semantic_fingerprint(value: Any) -> str:
    """Hash canonical semantic JSON, independent of display formatting."""

    return sha256(canonical(value))


def _strip_display_noise(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) < 3 or not lines[-1].strip().startswith("```"):
            raise FormatValidationError("unclosed code fence")
        opening = lines[0].strip()
        closing = lines[-1].strip()
        if not opening.startswith("```") or closing != "```":
            raise FormatValidationError("invalid code fence")
        text = "\n".join(lines[1:-1]).strip()
    # Models sometimes emphasize a JSON object in Markdown.  Only one pair at
    # the complete outer boundary is presentation noise.
    for marker in ("**", "__"):
        if text.startswith(marker) and text.endswith(marker) and len(text) > 4:
            text = text[len(marker) : -len(marker)].strip()
    return text


def _remove_trailing_commas(text: str) -> str:
    """Remove commas before ]/} while never touching quoted strings."""

    output: list[str] = []
    in_string = False
    escaped = False
    index = 0
    while index < len(text):
        char = text[index]
        if in_string:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            output.append(char)
            index += 1
            continue
        if char == ",":
            look = index + 1
            while look < len(text) and text[look].isspace():
                look += 1
            if look < len(text) and text[look] in "]}":
                index += 1
                continue
        output.append(char)
        index += 1
    return "".join(output)


def _unwrap_unique(value: Any) -> Any:
    if not isinstance(value, dict):
        raise FormatValidationError("response must decode to an object")
    # A single conventional wrapper is accepted, but two competing wrappers
    # are ambiguous and fail closed.  Semantic envelopes remain untouched.
    wrapper_keys = {"response", "result", "data", "json"}
    present = [key for key in value if key in wrapper_keys]
    if present:
        if len(value) != 1 or len(present) != 1 or not isinstance(value[present[0]], dict):
            raise FormatValidationError("response wrapper is not unique")
        value = value[present[0]]
    if not isinstance(value, dict):
        raise FormatValidationError("response must decode to an object")
    return value


def normalize_json_response(raw: Any) -> dict:
    """Parse one JSON object after finite, presentation-only normalization."""

    if isinstance(raw, dict):
        value = copy.deepcopy(raw)
    elif isinstance(raw, (bytes, bytearray)):
        try:
            value = json.loads(_remove_trailing_commas(_strip_display_noise(bytes(raw).decode("utf-8"))))
        except (UnicodeDecodeError, json.JSONDecodeError, FormatValidationError) as exc:
            raise FormatValidationError(f"invalid JSON response: {exc}") from exc
    elif isinstance(raw, str):
        try:
            value = json.loads(_remove_trailing_commas(_strip_display_noise(raw)))
        except (json.JSONDecodeError, FormatValidationError) as exc:
            raise FormatValidationError(f"invalid JSON response: {exc}") from exc
    else:
        raise FormatValidationError("response must be JSON text or object")
    return copy.deepcopy(_unwrap_unique(value))


@dataclass
class FormatRepairResult:
    value: dict | None
    valid: bool
    attempts: int = 0
    records: list[dict] = field(default_factory=list)
    error: str | None = None
    fingerprint: str | None = None

    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "valid": self.valid,
            "attempts": self.attempts,
            "records": copy.deepcopy(self.records),
            "error": self.error,
            "fingerprint": self.fingerprint,
        }


def _invoke_repairer(repairer: Any, prompt: str, raw: Any, error: str) -> Any:
    if repairer is None:
        return None
    if hasattr(repairer, "repair"):
        return repairer.repair(prompt, raw, error)
    if callable(repairer):
        return repairer(prompt, raw, error)
    raise TypeError("repairer must be callable or expose repair")


def format_json_with_repairs(
    raw: Any,
    repairer: Any = None,
    *,
    expected_fingerprint: str | None = None,
    max_repairs: int = 3,
    prompt: str = "Return the exact same JSON semantics with formatting repaired only.",
) -> FormatRepairResult:
    """Normalize a response and, if necessary, ask at most three format-only repairs.

    A repair is accepted only when its parsed semantic fingerprint equals the
    caller-provided fingerprint.  If the initial response cannot be parsed and
    no expected fingerprint is available, a repaired object cannot prove that
    semantics were preserved and is therefore rejected.
    """

    if isinstance(max_repairs, bool) or not isinstance(max_repairs, int) or not 0 <= max_repairs <= 3:
        raise ValueError("max_repairs must be an integer between 0 and 3")
    records: list[dict] = []
    current = raw
    last_error: str | None = None
    for attempt in range(max_repairs + 1):
        try:
            value = normalize_json_response(current)
            fingerprint = semantic_fingerprint(value)
            if expected_fingerprint is not None and fingerprint != expected_fingerprint:
                return FormatRepairResult(
                    value=value,
                    valid=False,
                    attempts=attempt,
                    records=records,
                    error="format repair changed semantic fingerprint",
                    fingerprint=fingerprint,
                )
            if attempt > 0 and expected_fingerprint is None:
                return FormatRepairResult(
                    value=value,
                    valid=False,
                    attempts=attempt,
                    records=records,
                    error="semantic invariance cannot be proven for repaired JSON",
                    fingerprint=fingerprint,
                )
            return FormatRepairResult(
                value=value,
                valid=True,
                attempts=attempt,
                records=records,
                fingerprint=fingerprint,
            )
        except FormatValidationError as exc:
            last_error = str(exc)
            if attempt >= max_repairs or repairer is None:
                break
            try:
                repaired = _invoke_repairer(repairer, prompt, current, last_error)
            except Exception as exc:
                records.append({"attempt": attempt + 1, "raw_response": None, "error": f"repairer failed: {exc}"})
                last_error = f"repairer failed: {exc}"
                break
            record = {"attempt": attempt + 1, "raw_response": getattr(repaired, "content", repaired), "error": last_error}
            request_record = getattr(repaired, "record", None)
            if isinstance(request_record, dict):
                record["request_record"] = copy.deepcopy(request_record)
            records.append(record)
            current = getattr(repaired, "content", repaired)
    return FormatRepairResult(
        value=None,
        valid=False,
        attempts=len(records),
        records=records,
        error=last_error or "invalid JSON response",
    )


# Public aliases make the seam easy to discover for callers using either
# wording from the plan or the shorter helper name.
format_json_response = format_json_with_repairs


__all__ = [
    "FormatRepairResult",
    "FormatValidationError",
    "format_json_response",
    "format_json_with_repairs",
    "normalize_json_response",
    "semantic_fingerprint",
]
