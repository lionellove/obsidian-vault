"""Dependency-free DeepSeek request/response seam for Stage 0.

The client has no dependency on the OpenAI SDK.  Tests inject a transport;
the default transport uses ``urllib`` over HTTPS.  API credentials are read
from the environment and are never included in request records or artifacts.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol
from urllib import error, request


MODEL_ID = "deepseek-v4-flash"
DEFAULT_BASE_URL = "https://api.deepseek.com"
META_EMPTY_MAX_ATTEMPTS = 3
META_RETRY_MAX_TOKEN_BUDGET = 8192
META_ROLE_RETRY_MAX_TOKEN_BUDGETS = {"s0_generator": 32768}
ROLE_DEFAULTS: dict[str, dict[str, Any]] = {
    "executor": {
        "thinking": {"type": "disabled"},
        "temperature": 0,
        "max_tokens": 128,
    },
    "s0_generator": {
        "thinking": {"type": "enabled"},
        "reasoning_effort": "max",
        "max_tokens": 2048,
    },
    "failure_analyzer": {
        "thinking": {"type": "enabled"},
        "reasoning_effort": "max",
        "max_tokens": 2048,
    },
    "success_analyzer": {
        "thinking": {"type": "enabled"},
        "reasoning_effort": "max",
        "max_tokens": 2048,
    },
    "root_cause_merger": {
        "thinking": {"type": "enabled"},
        "reasoning_effort": "max",
        "max_tokens": 2048,
    },
    "structured_patch": {
        "thinking": {"type": "enabled"},
        "reasoning_effort": "max",
        "max_tokens": 2048,
    },
    "full_rewrite": {
        "thinking": {"type": "enabled"},
        "reasoning_effort": "max",
        "max_tokens": 2048,
    },
    "semantic_verifier": {
        "thinking": {"type": "enabled"},
        "reasoning_effort": "max",
        "max_tokens": 2048,
    },
}

# These prompts are part of the frozen Stage 0 wire contract.  The context
# supplied by both candidate generators remains byte-identical; only the
# declared role instruction differs.  Keeping the instruction outside the
# user context makes it impossible for a generator to silently receive a
# different evidence bundle.
META_ROLE_PROMPTS: dict[str, str] = {
    "s0_generator": "You are the Stage 0 S0 generator. Return only the public Skill Package JSON described by the supplied schema. Never use task instances, trajectories, expert plans, or hidden state.",
    "failure_analyzer": "You are the Stage 0 failure analyzer. Return exactly one validated Failure IR JSON object from the public trajectory view; do not invent support or hidden execution facts.",
    "success_analyzer": "You are the Stage 0 success analyzer. Return exactly one validated Preservation IR JSON object from the public trajectory view; do not use expert or hidden state.",
    "root_cause_merger": "You are the Stage 0 root-cause merger. Return only validated root-cause candidates supported by the supplied Failure IR rows.",
    "structured_patch": "You are the Stage 0 Structured Semantic Patch generator. Return only a structured patch JSON (or explicit NO_PATCH) satisfying the supplied schema. Bind every edit to the selected root cause.",
    "full_rewrite": "You are the Stage 0 Full Rewrite generator. Return only a full-rewrite JSON (or explicit NO_PATCH) satisfying the supplied schema. The manifest must describe the complete deterministic rewrite diff.",
    "semantic_verifier": "You are the blind Stage 0 semantic verifier. Return only the seven numeric audit fields in the supplied schema. Do not infer the candidate method, generator label, or validation score.",
}

META_ROLE_SCHEMAS: dict[str, dict[str, Any]] = {
    "structured_patch": {"type": "object", "required": ["semantic_patch"], "additionalProperties": True},
    "full_rewrite": {"type": "object", "required": ["full_rewrite"], "additionalProperties": True},
    "semantic_verifier": {"type": "object", "required": ["relevance", "generality", "contradiction", "redundancy", "over_specificity", "root_cause_coverage", "preservation_risk"], "additionalProperties": False},
    "s0_generator": {"type": "object", "required": ["skill_package"], "additionalProperties": True},
    "failure_analyzer": {"type": "object", "required": ["failure_id", "trace_id", "task_id"], "additionalProperties": True},
    "success_analyzer": {"type": "object", "required": ["preservation_id", "trace_id", "task_id"], "additionalProperties": True},
    "root_cause_merger": {"type": "object", "required": ["root_causes"], "additionalProperties": False},
}

# DeepSeek JSON mode explicitly recommends an example of the requested JSON
# shape.  Values remain generic placeholders so the example cannot leak an
# ALFWorld task instance or privileged trajectory evidence.
META_ROLE_EXAMPLES: dict[str, dict[str, Any]] = {
    "s0_generator": {
        "skill_package": {
            "schema_version": "0.1",
            "package_id": "general-skill-package",
            "entry_node": "observe",
            "nodes": [
                {
                    "id": "observe",
                    "type": "decision",
                    "instruction": "Inspect the public observation and determine the next unmet subgoal.",
                    "scope": {"level": "global"},
                },
                {
                    "id": "select_object",
                    "type": "decision",
                    "instruction": "Select a generally described object relevant to the current subgoal.",
                    "scope": {"level": "global"},
                },
                {
                    "id": "acquire",
                    "type": "action",
                    "instruction": "Choose one admissible action that advances object acquisition.",
                    "scope": {"level": "global"},
                },
                {
                    "id": "transform",
                    "type": "action",
                    "instruction": "Apply a required state transformation only when the goal requires it.",
                    "scope": {"level": "global"},
                },
                {
                    "id": "place",
                    "type": "action",
                    "instruction": "Choose one admissible action that advances placement at the goal receptacle.",
                    "scope": {"level": "global"},
                },
                {
                    "id": "verify",
                    "type": "verification",
                    "instruction": "Verify goal progress from the latest public observation.",
                    "scope": {"level": "global"},
                },
            ],
            "edges": [
                {"id": "e1", "source": "observe", "target": "select_object", "condition": "a subgoal remains"},
                {"id": "e2", "source": "select_object", "target": "acquire", "condition": "an object is selected"},
                {"id": "e3", "source": "acquire", "target": "transform", "condition": "acquisition is established"},
                {"id": "e4", "source": "transform", "target": "place", "condition": "required state is established or unnecessary"},
                {"id": "e5", "source": "place", "target": "verify", "condition": "placement was attempted"},
            ],
            "constraints": [
                {
                    "id": "c1",
                    "scope": {"level": "global"},
                    "rule": "Choose exactly one currently admissible environment action.",
                }
            ],
            "verifications": [
                {
                    "id": "v1",
                    "target": "verify",
                    "criterion": "The latest observation supports completion or identifies the next unmet subgoal.",
                    "on_failure": "f1",
                    "scope": {"level": "global"},
                }
            ],
            "fallbacks": [
                {
                    "id": "f1",
                    "trigger": "The latest action did not establish the expected progress.",
                    "target": "observe",
                    "max_retries": 1,
                    "scope": {"level": "global"},
                }
            ],
        }
    },
    "failure_analyzer": {"failure_id": "<id>", "trace_id": "<trace>", "task_id": "<task>"},
    "success_analyzer": {"preservation_id": "<id>", "trace_id": "<trace>", "task_id": "<task>"},
    "root_cause_merger": {"root_causes": []},
    "structured_patch": {"semantic_patch": {"root_cause_id": "<id>", "edits": []}},
    "full_rewrite": {
        "full_rewrite": {
            "root_cause_id": "<id>",
            "rewritten_skill_package": {},
            "change_manifest": [],
        }
    },
    "semantic_verifier": {
        "relevance": 0.0,
        "generality": 0.0,
        "contradiction": 0.0,
        "redundancy": 0.0,
        "over_specificity": 0.0,
        "root_cause_coverage": 0.0,
        "preservation_risk": 0.0,
    },
}


class DeepSeekAPIError(RuntimeError):
    """A request or response failed closed."""


class JSONTransport(Protocol):
    def post_json(
        self,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout: float,
    ) -> "TransportResponse | Mapping[str, Any]":
        ...


@dataclass(frozen=True)
class TransportResponse:
    status_code: int
    headers: Mapping[str, str]
    body: Mapping[str, Any]


class HTTPSJSONTransport:
    """Small real HTTPS JSON transport used only outside offline tests."""

    def post_json(
        self,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout: float,
    ) -> TransportResponse:
        if not url.casefold().startswith("https://"):
            raise ValueError("DeepSeek transport requires an HTTPS URL")
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json", **dict(headers)},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=timeout) as response:
                raw = response.read()
                decoded = json.loads(raw.decode("utf-8"))
                if not isinstance(decoded, dict):
                    raise DeepSeekAPIError("DeepSeek response JSON must be an object")
                return TransportResponse(
                    status_code=int(getattr(response, "status", 200)),
                    headers={str(k): str(v) for k, v in response.headers.items()},
                    body=decoded,
                )
        except DeepSeekAPIError:
            raise
        except error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")[:1000]
            raise DeepSeekAPIError(f"DeepSeek HTTP {exc.code}: {details}") from exc
        except (error.URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DeepSeekAPIError(f"DeepSeek HTTPS request failed: {exc}") from exc


@dataclass(frozen=True)
class LLMResult:
    content: str
    record: dict[str, Any]
    raw_response: Mapping[str, Any]

    @property
    def usage(self) -> Mapping[str, Any]:
        return self.record.get("usage", {})

    @property
    def request_record(self) -> dict[str, Any]:
        return self.record


def _first_present(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _extract_content(response: Mapping[str, Any]) -> str:
    choices = response.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, Mapping):
            message = first.get("message", first)
            if isinstance(message, Mapping):
                content = message.get("content", "")
                if isinstance(content, list):
                    content = "".join(
                        str(part.get("text", ""))
                        for part in content
                        if isinstance(part, Mapping)
                    )
                if isinstance(content, str):
                    return content
    direct = response.get("content")
    if isinstance(direct, str):
        return direct
    message = response.get("message")
    if isinstance(message, Mapping) and isinstance(message.get("content"), str):
        return message["content"]
    return ""


def _normalize_usage(response: Mapping[str, Any]) -> dict[str, Any]:
    usage = response.get("usage")
    if not isinstance(usage, Mapping):
        usage = {}
    reasoning_tokens = _first_present(usage, "reasoning_tokens")
    completion_details = usage.get("completion_tokens_details")
    if isinstance(completion_details, Mapping):
        nested_reasoning_tokens = _first_present(completion_details, "reasoning_tokens")
        if nested_reasoning_tokens is not None:
            reasoning_tokens = nested_reasoning_tokens
    return {
        "prompt_tokens": _first_present(usage, "prompt_tokens", "input_tokens"),
        "cache_hit_tokens": _first_present(
            usage, "prompt_cache_hit_tokens", "cache_hit_tokens", "cache_read_input_tokens"
        ),
        "cache_miss_tokens": _first_present(
            usage, "prompt_cache_miss_tokens", "cache_miss_tokens", "cache_creation_input_tokens"
        ),
        "reasoning_tokens": reasoning_tokens,
        "output_tokens": _first_present(usage, "completion_tokens", "output_tokens"),
    }


def _header(headers: Mapping[str, str], *wanted: str) -> str | None:
    normalized = {str(k).casefold(): str(v) for k, v in headers.items()}
    for key in wanted:
        if key.casefold() in normalized:
            return normalized[key.casefold()]
    return None


class DeepSeekClient:
    """Injectable DeepSeek client with auditable request records."""

    def __init__(
        self,
        *,
        transport: JSONTransport | None = None,
        api_key_env: str = "DEEPSEEK_API_KEY",
        api_key: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        model: str = MODEL_ID,
        timeout: float = 120.0,
    ) -> None:
        self.transport = transport or HTTPSJSONTransport()
        self.api_key = api_key if api_key is not None else os.environ.get(api_key_env, "").strip()
        if transport is None and not self.api_key:
            raise ValueError(f"Missing required environment variable: {api_key_env}")
        if not base_url.casefold().startswith("https://"):
            raise ValueError("DeepSeek base_url must use HTTPS")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = float(timeout)
        self.request_records: list[dict[str, Any]] = []
        # Short aliases make the audit seam convenient without duplicating
        # mutable state.
        self.records = self.request_records
        self.request_log = self.request_records

    def build_request(
        self,
        *,
        role: str,
        messages: list[Mapping[str, str]],
        token_budget: int | None = None,
        response_format: Mapping[str, Any] | None = None,
        stage0_schema: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if role not in ROLE_DEFAULTS:
            raise ValueError(f"unknown DeepSeek role: {role}")
        if not isinstance(messages, list) or not messages:
            raise ValueError("messages must be a non-empty list")
        defaults = ROLE_DEFAULTS[role]
        max_tokens = defaults["max_tokens"] if token_budget is None else token_budget
        if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or max_tokens <= 0:
            raise ValueError("token_budget must be a positive integer")
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [dict(message) for message in messages],
            "thinking": dict(defaults["thinking"]),
            "max_tokens": max_tokens,
        }
        if "temperature" in defaults:
            body["temperature"] = defaults["temperature"]
        if "reasoning_effort" in defaults:
            body["reasoning_effort"] = defaults["reasoning_effort"]
        if response_format is not None:
            body["response_format"] = dict(response_format)
        # DeepSeek JSON mode accepts only the standard response_format field
        # on the wire.  The local schema envelope is recorded by ``complete``
        # and rendered into the frozen system prompt by ``complete_meta``;
        # never send a provider-unknown top-level field.
        return body

    def complete(
        self,
        *,
        role: str,
        messages: list[Mapping[str, str]],
        token_budget: int | None = None,
        response_format: Mapping[str, Any] | None = None,
        stage0_schema: Mapping[str, Any] | None = None,
    ) -> LLMResult:
        body = self.build_request(
            role=role,
            messages=messages,
            token_budget=token_budget,
            response_format=response_format,
            stage0_schema=stage0_schema,
        )
        timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        started = time.perf_counter()
        record: dict[str, Any] = {
            "timestamp_utc": timestamp,
            "role": role,
            "request_body": body,
            "model": None,
            "system_fingerprint": None,
            "request_id": None,
            "usage": {
                "prompt_tokens": None,
                "cache_hit_tokens": None,
                "cache_miss_tokens": None,
                "reasoning_tokens": None,
                "output_tokens": None,
            },
            "latency_seconds": None,
            "raw_response": None,
        }
        if stage0_schema is not None:
            record["schema_envelope"] = json.loads(json.dumps(stage0_schema, ensure_ascii=False, sort_keys=True))
        record["request"] = body
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            if hasattr(self.transport, "post_json"):
                response = self.transport.post_json(
                    self.base_url + "/chat/completions",
                    headers,
                    body,
                    self.timeout,
                )
            elif hasattr(self.transport, "request"):
                response = self.transport.request(
                    self.base_url + "/chat/completions",
                    headers,
                    body,
                    self.timeout,
                )
            elif callable(self.transport):
                response = self.transport(
                    self.base_url + "/chat/completions",
                    headers,
                    body,
                    self.timeout,
                )
            else:
                raise DeepSeekAPIError("transport must provide post_json, request, or __call__")
            if isinstance(response, TransportResponse):
                response_body = response.body
                response_headers = response.headers
                record["status_code"] = response.status_code
            elif isinstance(response, Mapping):
                response_body = response
                response_headers = {}
                record["status_code"] = 200
            else:
                raise DeepSeekAPIError("transport returned an invalid response object")
            if isinstance(response_body, (bytes, bytearray, str)):
                try:
                    response_body = json.loads(response_body)
                except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise DeepSeekAPIError("DeepSeek response body was not valid JSON") from exc
            if not isinstance(response_body, Mapping):
                raise DeepSeekAPIError("DeepSeek response body must be an object")
            record["raw_response"] = dict(response_body)
            record["model"] = response_body.get("model")
            record["system_fingerprint"] = response_body.get("system_fingerprint")
            record["request_id"] = (
                _header(response_headers, "x-request-id", "request-id")
                or response_body.get("request_id")
                or response_body.get("id")
            )
            record["usage"] = _normalize_usage(response_body)
            choices = response_body.get("choices")
            first_choice = choices[0] if isinstance(choices, list) and choices else None
            finish_reason = first_choice.get("finish_reason") if isinstance(first_choice, Mapping) else None
            record["finish_reason"] = finish_reason
            content = _extract_content(response_body).strip()
            if finish_reason == "length":
                raise DeepSeekAPIError("DeepSeek response was truncated at max_tokens")
            if not content:
                raise DeepSeekAPIError("DeepSeek response contained empty content")
            record["latency_seconds"] = time.perf_counter() - started
            self.request_records.append(record)
            return LLMResult(content=content, record=record, raw_response=dict(response_body))
        except DeepSeekAPIError as exc:
            record["error"] = str(exc)
            record["latency_seconds"] = time.perf_counter() - started
            self.request_records.append(record)
            raise
        except Exception as exc:
            record["error"] = repr(exc)
            record["latency_seconds"] = time.perf_counter() - started
            self.request_records.append(record)
            raise DeepSeekAPIError(f"DeepSeek request failed: {exc}") from exc

    def complete_meta(self, *, role: str, context: str, token_budget: int) -> LLMResult:
        # All semantic Stage 0 roles use the same meta/thinking contract.  The
        # executor is intentionally excluded: it has its own disabled-thinking
        # low-latency request seam.
        if role not in ROLE_DEFAULTS or role == "executor":
            raise ValueError("complete_meta role must be a semantic meta role")
        if ROLE_DEFAULTS[role].get("thinking", {}).get("type") != "enabled":
            raise ValueError("complete_meta requires thinking.type=enabled")
        if not isinstance(context, str):
            context = json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        schema = META_ROLE_SCHEMAS[role]
        system_prompt = (
            META_ROLE_PROMPTS[role]
            + "\nThe response must be valid JSON. Local schema contract (enforced after the response):\n"
            + json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\nExample JSON output shape:\n"
            + json.dumps(META_ROLE_EXAMPLES[role], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
        for attempt in range(1, META_EMPTY_MAX_ATTEMPTS + 1):
            configured_ceiling = META_ROLE_RETRY_MAX_TOKEN_BUDGETS.get(
                role, META_RETRY_MAX_TOKEN_BUDGET
            )
            retry_budget_ceiling = max(token_budget, configured_ceiling)
            attempt_token_budget = min(token_budget * (2 ** (attempt - 1)), retry_budget_ceiling)
            attempt_prompt = system_prompt
            if attempt > 1:
                attempt_prompt += (
                    "\nProvider retry instruction: The previous provider response was empty or truncated. "
                    "Return exactly one non-empty JSON object now; do not emit only reasoning or whitespace."
                )
            try:
                result = self.complete(
                    role=role,
                    messages=[
                        {"role": "system", "content": attempt_prompt},
                        {"role": "user", "content": context},
                    ],
                    token_budget=attempt_token_budget,
                    response_format={"type": "json_object"},
                    stage0_schema={"name": f"stage0_{role}", "schema": schema},
                )
            except DeepSeekAPIError as exc:
                if self.request_records:
                    self.request_records[-1]["attempt"] = attempt
                    self.request_records[-1]["max_attempts"] = META_EMPTY_MAX_ATTEMPTS
                if str(exc) not in {
                    "DeepSeek response contained empty content",
                    "DeepSeek response was truncated at max_tokens",
                }:
                    raise
                if attempt == META_EMPTY_MAX_ATTEMPTS:
                    raise DeepSeekAPIError(f"{exc} after {META_EMPTY_MAX_ATTEMPTS} attempts") from exc
                continue
            result.record["attempt"] = attempt
            result.record["max_attempts"] = META_EMPTY_MAX_ATTEMPTS
            return result
        raise AssertionError("unreachable DeepSeek meta retry state")
