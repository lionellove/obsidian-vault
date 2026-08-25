from contextlib import contextmanager

try:
    import pytest  # type: ignore
except ImportError:
    pytest = None

from stage0_episode import EpisodeRunner
from stage0_executor import ExecutorOutputError


@contextmanager
def _raises(exc_type):
    try:
        yield
    except exc_type:
        return
    raise AssertionError(f"expected {exc_type.__name__}")


def raises(exc_type):
    return pytest.raises(exc_type) if pytest is not None else _raises(exc_type)


class FakeEnv:
    def __init__(self, actions=("look",), done=True):
        self.actions = list(actions)
        self.done = done
        self.executed = []

    def reset(self):
        return "Your task is to: inspect the room", {
            "admissible_commands": [self.actions],
            "extra.gamefile": ["pick_and_place_simple-Vase-None-Safe-1/trial_T/game.tw-pddl"],
        }

    def step(self, action):
        self.executed.append(action)
        return "Done.", 1.0, self.done, {
            "admissible_commands": [self.actions if not self.done else []],
            "won": [self.done],
            "extra.gamefile": ["pick_and_place_simple-Vase-None-Safe-1/trial_T/game.tw-pddl"],
        }


class FakeExecutor:
    skill_text = "SKILL TEXT"
    skill_hash = "skill-hash"

    def __init__(self, action="look"):
        self.action = action
        self.calls = []

    def decide(self, task_goal, observation, admissible_actions, trajectory):
        self.calls.append((task_goal, observation, list(admissible_actions), list(trajectory)))
        return type("Decision", (), {
            "action": self.action,
            "raw_response": "FINAL_ACTION: look",
            "request_record": {
                "request_id": "r1",
                "usage": {
                    "prompt_tokens": 2,
                    "cache_hit_tokens": 0,
                    "cache_miss_tokens": 2,
                    "reasoning_tokens": 0,
                    "output_tokens": 1,
                },
            },
        })()


def test_episode_executes_only_parsed_action_and_records_skill_request_and_tokens():
    env = FakeEnv()
    result = EpisodeRunner(env, FakeExecutor()).run(task_id="task-relative")
    assert result["success"] is True
    assert result["termination"] == "success"
    assert env.executed == ["look"]
    row = result["trajectory"][0]
    assert row["observation"] == "Your task is to: inspect the room"
    assert row["raw_model_response"] == "FINAL_ACTION: look"
    assert row["executed_action"] == "look"
    assert row["reward"] == 1.0
    assert row["done"] is True
    assert row["skill_text"] == "SKILL TEXT"
    assert row["skill_hash"] == "skill-hash"
    assert row["request_record"]["request_id"] == "r1"
    assert row["tokens"]["output_tokens"] == 1
    assert result["request_records"][0]["request_id"] == "r1"


def test_invalid_output_is_fail_closed_and_never_steps_environment():
    class InvalidExecutor(FakeExecutor):
        def decide(self, *args):
            raise ExecutorOutputError("bad", raw_response="FINAL_ACTION: invented", request_record={"request_id": "bad"})

    env = FakeEnv()
    result = EpisodeRunner(env, InvalidExecutor()).run()
    assert result["success"] is False
    assert result["termination"] == "invalid_model_output"
    assert env.executed == []
    assert result["trajectory"][0]["executed_action"] is None
    assert result["trajectory"][0]["raw_model_response"] == "FINAL_ACTION: invented"


def test_episode_rechecks_executor_action_membership_before_step():
    class InventedExecutor(FakeExecutor):
        def decide(self, *args):
            return type("Decision", (), {
                "action": "invented",
                "raw_response": "FINAL_ACTION: invented",
                "request_record": {"request_id": "bad", "usage": {}},
            })()

    env = FakeEnv()
    result = EpisodeRunner(env, InventedExecutor()).run()
    assert result["termination"] == "invalid_model_output"
    assert env.executed == []


def test_no_actions_and_max_steps_are_fail_closed():
    no_actions = FakeEnv(actions=(), done=True)
    no_action_result = EpisodeRunner(no_actions, FakeExecutor()).run()
    assert no_action_result["termination"] == "no_admissible_actions"
    assert no_action_result["success"] is False

    looping = FakeEnv(done=False)
    looping_result = EpisodeRunner(looping, FakeExecutor(), max_steps=2).run()
    assert looping_result["termination"] == "max_steps"
    assert looping_result["success"] is False
    assert len(looping_result["trajectory"]) == 2
    assert len(looping.executed) == 2


def test_max_steps_cannot_exceed_plan_limit():
    with raises(ValueError):
        EpisodeRunner(FakeEnv(), FakeExecutor(), max_steps=51)
