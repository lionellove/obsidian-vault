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


def test_meta_roles_share_context_and_budget_and_enable_max_thinking():
    transport = FakeTransport()
    client = DeepSeekClient(transport=transport, api_key="secret")
    context = "same evidence context"
    client.complete_meta(role="structured_patch", context=context, token_budget=777)
    client.complete_meta(role="full_rewrite", context=context, token_budget=777)
    first, second = [call["payload"] for call in transport.calls]
    assert first["messages"] == second["messages"]
    assert first["max_tokens"] == second["max_tokens"] == 777
    assert first["thinking"] == second["thinking"] == {"type": "enabled"}
    assert first["reasoning_effort"] == second["reasoning_effort"] == "max"


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
