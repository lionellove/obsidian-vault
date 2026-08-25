from contextlib import contextmanager

try:
    import pytest  # type: ignore
except ImportError:
    pytest = None

from stage0_executor import (
    Executor,
    ExecutorOutputError,
    build_executor_prompt,
    parse_executor_action,
)


@contextmanager
def _raises(exc_type):
    try:
        yield
    except exc_type:
        return
    raise AssertionError(f"expected {exc_type.__name__}")


def raises(exc_type):
    return pytest.raises(exc_type) if pytest is not None else _raises(exc_type)


def test_strict_parser_accepts_only_one_marked_exact_action():
    actions = ["look", "take mug 1"]
    assert parse_executor_action("  FINAL_ACTION: look  ", actions) == "look"
    assert parse_executor_action("```text\n**FINAL_ACTION: `look`**\n```", actions) == "look"
    with raises(ExecutorOutputError):
        parse_executor_action("look", actions)
    with raises(ExecutorOutputError):
        parse_executor_action("FINAL_ACTION: 0", actions)
    with raises(ExecutorOutputError):
        parse_executor_action("FINAL_ACTION: take mug", actions)
    with raises(ExecutorOutputError):
        parse_executor_action("FINAL_ACTION: look\nFINAL_ACTION: look", actions)
    with raises(ExecutorOutputError):
        parse_executor_action("FINAL_ACTION: LOOK", actions)


def test_parser_rejects_duplicate_admissible_mapping_and_noise():
    with raises(ExecutorOutputError):
        parse_executor_action("FINAL_ACTION: look", ["look", "look"])
    with raises(ExecutorOutputError):
        parse_executor_action("analysis\nFINAL_ACTION: look", ["look"])
    with raises(ExecutorOutputError):
        parse_executor_action("FINAL_ACTION: look\nExplanation", ["look"])


def test_prompt_includes_goal_observation_actions_trajectory_and_skill():
    prompt = build_executor_prompt(
        task_goal="inspect the room",
        observation="You are in the kitchen.",
        admissible_actions=["look"],
        trajectory=[{"step": 1, "executed_action": "open fridge", "next_observation": "fridge open"}],
        skill_text="SKILL PACKAGE demo",
    )
    for text in ("inspect the room", "You are in the kitchen.", "look", "open fridge", "fridge open", "SKILL PACKAGE demo"):
        assert text in prompt


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class FakeResult:
    content = "FINAL_ACTION: look"
    record = {"usage": {"output_tokens": 1}, "request_id": "r1"}


def test_executor_returns_original_admissible_string_and_request_record():
    client = FakeClient(FakeResult())
    executor = Executor(client=client, skill_text="SKILL", token_budget=128)
    decision = executor.decide("inspect", "room", ["look"], [])
    assert decision.action == "look"
    assert decision.raw_response == "FINAL_ACTION: look"
    assert decision.request_record["request_id"] == "r1"
    assert client.calls[0]["role"] == "executor"
    assert "SKILL" in client.calls[0]["messages"][0]["content"]


def test_executor_propagates_invalid_output_without_action():
    class InvalidResult:
        content = "FINAL_ACTION: invented action"
        record = {"request_id": "bad"}

    executor = Executor(client=FakeClient(InvalidResult()), skill_text="SKILL")
    with raises(ExecutorOutputError):
        executor.decide("inspect", "room", ["look"], [])


def test_executor_wraps_request_failure_with_last_audit_record():
    class FailingClient:
        request_records = [{"error": "network", "request_id": "failed"}]

        def complete(self, **kwargs):
            raise RuntimeError("network")

    from stage0_executor import ExecutorRequestError

    executor = Executor(client=FailingClient(), skill_text="SKILL")
    with raises(ExecutorRequestError):
        executor.decide("inspect", "room", ["look"], [])
