import json
import os
from contextlib import contextmanager

try:
    import pytest  # type: ignore
except ImportError:
    pytest = None

from stage0_llm import DeepSeekAPIError, DeepSeekClient, TransportResponse


@contextmanager
def _raises(exc_type):
    try:
        yield
    except exc_type:
        return
    raise AssertionError(f"expected {exc_type.__name__}")


def raises(exc_type):
    return pytest.raises(exc_type) if pytest is not None else _raises(exc_type)


class FakeTransport:
    def __init__(self, response=None, error=None):
        self.response = response or {
            "id": "resp_1",
            "model": "deepseek-v4-flash",
            "system_fingerprint": "fp_1",
            "choices": [{"message": {"content": "ok"}}],
            "usage": {
                "prompt_tokens": 11,
                "prompt_cache_hit_tokens": 3,
                "prompt_cache_miss_tokens": 8,
                "reasoning_tokens": 5,
                "completion_tokens": 7,
            },
        }
        self.error = error
        self.calls = []

    def post_json(self, url, headers, payload, timeout):
        self.calls.append({"url": url, "headers": dict(headers), "payload": payload, "timeout": timeout})
        if self.error:
            raise self.error
        return TransportResponse(
            status_code=200,
            headers={"X-Request-ID": "header_req_1"},
            body=self.response,
        )


class SequenceTransport:
    """Provider boundary fixture returning one response per request."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post_json(self, url, headers, payload, timeout):
        self.calls.append({"url": url, "headers": dict(headers), "payload": payload, "timeout": timeout})
        response = self.responses.pop(0)
        return TransportResponse(
            status_code=200,
            headers={"X-Request-ID": f"retry_req_{len(self.calls)}"},
            body=response,
        )


def test_executor_request_contract_and_response_metadata():
    transport = FakeTransport()
    client = DeepSeekClient(transport=transport, api_key="secret-for-memory-only")
    result = client.complete(
        role="executor",
        messages=[{"role": "user", "content": "choose"}],
    )
    body = transport.calls[0]["payload"]
    assert body["model"] == "deepseek-v4-flash"
    assert body["thinking"] == {"type": "disabled"}
    assert body["temperature"] == 0
    assert body["max_tokens"] <= 256
    assert result.content == "ok"
    record = result.record
    assert record["model"] == "deepseek-v4-flash"
    assert record["system_fingerprint"] == "fp_1"
    assert record["request_id"] == "header_req_1"
    assert record["usage"] == {
        "prompt_tokens": 11,
        "cache_hit_tokens": 3,
        "cache_miss_tokens": 8,
        "reasoning_tokens": 5,
        "output_tokens": 7,
    }
    assert record["latency_seconds"] >= 0
    assert record["timestamp_utc"].endswith("Z")
    assert "secret-for-memory-only" not in json.dumps(record)


def test_official_completion_tokens_details_reasoning_usage_is_normalized():
    transport = FakeTransport(
        response={
            "id": "resp_official_usage",
            "model": "deepseek-v4-flash",
            "system_fingerprint": "fp_official",
            "choices": [{"message": {"content": "ok"}}],
            "usage": {
                "prompt_tokens": 21,
                "prompt_cache_hit_tokens": 4,
                "prompt_cache_miss_tokens": 17,
                "completion_tokens": 13,
                "completion_tokens_details": {"reasoning_tokens": 9},
            },
        }
    )
    result = DeepSeekClient(transport=transport, api_key="secret").complete(
        role="executor",
        messages=[{"role": "user", "content": "choose"}],
    )

    assert result.record["usage"] == {
        "prompt_tokens": 21,
        "cache_hit_tokens": 4,
        "cache_miss_tokens": 17,
        "reasoning_tokens": 9,
        "output_tokens": 13,
    }


def test_meta_roles_share_context_and_budget_and_enable_max_thinking():
    transport = FakeTransport()
    client = DeepSeekClient(transport=transport, api_key="secret")
    context = "same evidence context"
    client.complete_meta(role="structured_patch", context=context, token_budget=777)
    client.complete_meta(role="full_rewrite", context=context, token_budget=777)
    first, second = [call["payload"] for call in transport.calls]
    assert first["messages"][1] == second["messages"][1]
    assert first["messages"][0]["role"] == second["messages"][0]["role"] == "system"
    assert first["messages"][0]["content"] != second["messages"][0]["content"]
    assert first["response_format"] == second["response_format"] == {"type": "json_object"}
    assert "stage0_schema" not in first
    assert "stage0_schema" not in second
    assert "schema" in first["messages"][0]["content"].casefold()
    assert "schema" in second["messages"][0]["content"].casefold()
    assert first["max_tokens"] == second["max_tokens"] == 777
    assert first["thinking"] == second["thinking"] == {"type": "enabled"}
    assert first["reasoning_effort"] == second["reasoning_effort"] == "max"


def test_meta_json_empty_content_is_retried_and_all_attempts_are_audited():
    empty = {
        "id": "empty",
        "model": "deepseek-v4-flash",
        "system_fingerprint": "fp_retry",
        "choices": [{"finish_reason": "stop", "message": {"content": "", "reasoning_content": "thinking"}}],
        "usage": {
            "prompt_tokens": 10,
            "prompt_cache_hit_tokens": 0,
            "prompt_cache_miss_tokens": 10,
            "completion_tokens": 4,
            "completion_tokens_details": {"reasoning_tokens": 4},
        },
    }
    success = {
        "id": "success",
        "model": "deepseek-v4-flash",
        "system_fingerprint": "fp_retry",
        "choices": [{"finish_reason": "stop", "message": {"content": '{"skill_package": {}}'}}],
        "usage": {
            "prompt_tokens": 12,
            "prompt_cache_hit_tokens": 8,
            "prompt_cache_miss_tokens": 4,
            "completion_tokens": 5,
            "completion_tokens_details": {"reasoning_tokens": 1},
        },
    }
    transport = SequenceTransport([empty, empty, success])
    client = DeepSeekClient(transport=transport, api_key="secret")

    result = client.complete_meta(role="s0_generator", context={}, token_budget=64)

    assert result.content == '{"skill_package": {}}'
    assert len(transport.calls) == 3
    assert [call["payload"]["max_tokens"] for call in transport.calls] == [64, 128, 256]
    assert len(client.request_records) == 3
    assert [record["attempt"] for record in client.request_records] == [1, 2, 3]
    assert all(record["max_attempts"] == 3 for record in client.request_records)
    assert client.request_records[0]["error"] == "DeepSeek response contained empty content"
    assert client.request_records[0]["raw_response"]["choices"][0]["finish_reason"] == "stop"
    assert client.request_records[0]["usage"]["reasoning_tokens"] == 4
    assert "previous provider response was empty" in transport.calls[1]["payload"]["messages"][0]["content"].casefold()
    assert transport.calls[0]["payload"]["messages"][1] == transport.calls[2]["payload"]["messages"][1]
    assert "secret" not in json.dumps(client.request_records)


def test_meta_json_empty_content_stops_after_three_attempts():
    empty = {
        "id": "always_empty",
        "model": "deepseek-v4-flash",
        "system_fingerprint": "fp_retry",
        "choices": [{"finish_reason": "stop", "message": {"content": ""}}],
        "usage": {
            "prompt_tokens": 1,
            "prompt_cache_hit_tokens": 0,
            "prompt_cache_miss_tokens": 1,
            "completion_tokens": 0,
        },
    }
    transport = SequenceTransport([empty, empty, empty])
    client = DeepSeekClient(transport=transport, api_key="secret")

    try:
        client.complete_meta(role="s0_generator", context={}, token_budget=64)
    except DeepSeekAPIError as exc:
        assert str(exc) == "DeepSeek response contained empty content after 3 attempts"
    else:
        raise AssertionError("expected bounded empty-content failure")

    assert len(transport.calls) == 3
    assert len(client.request_records) == 3
    assert all(record["raw_response"]["id"] == "always_empty" for record in client.request_records)


def test_s0_length_truncation_retries_expand_beyond_initial_safe_budget():
    empty_at_length = {
        "id": "length",
        "model": "deepseek-v4-flash",
        "choices": [
            {
                "finish_reason": "length",
                "message": {"content": "", "reasoning_content": "thinking"},
            }
        ],
        "usage": {"completion_tokens": 8192},
    }
    success = {
        "id": "success",
        "model": "deepseek-v4-flash",
        "choices": [{"finish_reason": "stop", "message": {"content": '{"skill_package": {}}'}}],
        "usage": {},
    }
    transport = SequenceTransport([empty_at_length, empty_at_length, success])
    client = DeepSeekClient(transport=transport, api_key="secret")

    result = client.complete_meta(role="s0_generator", context={}, token_budget=8192)

    assert result.content == '{"skill_package": {}}'
    assert [call["payload"]["max_tokens"] for call in transport.calls] == [8192, 16384, 32768]


def test_nonempty_truncated_json_is_retried_before_local_validation():
    truncated = {
        "id": "truncated",
        "model": "deepseek-v4-flash",
        "choices": [
            {
                "finish_reason": "length",
                "message": {"content": '{"skill_package": {}}', "reasoning_content": "thinking"},
            }
        ],
        "usage": {"completion_tokens": 8192},
    }
    success = {
        "id": "success",
        "model": "deepseek-v4-flash",
        "choices": [{"finish_reason": "stop", "message": {"content": '{"skill_package": {"done": true}}'}}],
        "usage": {},
    }
    transport = SequenceTransport([truncated, success])
    client = DeepSeekClient(transport=transport, api_key="secret")

    result = client.complete_meta(role="s0_generator", context={}, token_budget=8192)

    assert result.content == '{"skill_package": {"done": true}}'
    assert [call["payload"]["max_tokens"] for call in transport.calls] == [8192, 16384]
    assert client.request_records[0]["error"] == "DeepSeek response was truncated at max_tokens"


def test_meta_json_initial_prompt_contains_an_example_output_shape():
    transport = FakeTransport(
        response={
            "model": "deepseek-v4-flash",
            "choices": [{"message": {"content": '{"skill_package": {}}'}}],
            "usage": {},
        }
    )
    client = DeepSeekClient(transport=transport, api_key="secret")

    client.complete_meta(role="s0_generator", context={}, token_budget=64)

    system_prompt = transport.calls[0]["payload"]["messages"][0]["content"]
    assert "example json output" in system_prompt.casefold()
    assert '"skill_package"' in system_prompt


def test_s0_example_describes_every_artifact_object_shape():
    transport = FakeTransport(
        response={
            "model": "deepseek-v4-flash",
            "choices": [{"message": {"content": '{"skill_package": {}}'}}],
            "usage": {},
        }
    )
    client = DeepSeekClient(transport=transport, api_key="secret")

    client.complete_meta(role="s0_generator", context={}, token_budget=64)

    system_prompt = transport.calls[0]["payload"]["messages"][0]["content"]
    assert '"constraints":[{' in system_prompt
    assert '"verifications":[{' in system_prompt
    assert '"fallbacks":[{' in system_prompt
    for required_field in ('"rule"', '"criterion"', '"on_failure"', '"trigger"', '"max_retries"'):
        assert required_field in system_prompt


def test_api_error_is_recorded_without_secret():
    transport = FakeTransport(error=RuntimeError("offline failure"))
    client = DeepSeekClient(transport=transport, api_key="do-not-record")
    with raises(DeepSeekAPIError):
        client.complete(role="executor", messages=[{"role": "user", "content": "x"}])
    assert len(client.request_records) == 1
    record = client.request_records[0]
    assert "offline failure" in record["error"]
    assert "do-not-record" not in json.dumps(record)


def test_real_transport_is_https_only_without_network_call():
    from stage0_llm import HTTPSJSONTransport

    with raises(ValueError):
        HTTPSJSONTransport().post_json("http://localhost", {}, {}, 1)
