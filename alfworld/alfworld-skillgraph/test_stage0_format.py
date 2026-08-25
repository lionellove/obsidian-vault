"""Public behavior tests for deterministic response formatting."""

from __future__ import annotations

from stage0_format import (
    format_json_with_repairs,
    semantic_fingerprint,
    normalize_json_response,
)


def test_normalize_json_response_accepts_one_display_wrapper_and_trailing_comma():
    raw = "```json\n{\"edits\": [{\"op\": \"ADD\",}],}\n```"
    value = normalize_json_response(raw)
    assert value == {"edits": [{"op": "ADD"}]}


def test_format_repair_succeeds_without_changing_semantics():
    expected = {"status": "NO_PATCH", "reason": "already covered"}
    repaired = '{"status":"NO_PATCH","reason":"already covered"}'
    calls = []

    def repairer(prompt, raw, error):
        calls.append((prompt, raw, error))
        return repaired

    result = format_json_with_repairs(
        "not json",
        repairer,
        expected_fingerprint=semantic_fingerprint(expected),
    )
    assert result.valid is True
    assert result.value == expected
    assert len(calls) == 1
    assert result.attempts == 1


def test_format_repair_rejects_semantic_tampering_and_limits_attempts():
    expected = {"status": "NO_PATCH", "reason": "already covered"}

    def tamper(prompt, raw, error):
        return '{"status":"NO_PATCH","reason":"changed"}'

    tampered = format_json_with_repairs(
        "not json",
        tamper,
        expected_fingerprint=semantic_fingerprint(expected),
    )
    assert tampered.valid is False
    assert "semantic" in tampered.error.lower()

    count = []

    def forever(prompt, raw, error):
        count.append(1)
        return "still not json"

    limited = format_json_with_repairs("not json", forever, max_repairs=3)
    assert limited.valid is False
    assert len(count) == 3
    assert limited.attempts == 3

