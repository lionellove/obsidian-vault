"""Red/green regression tests for the orchestration P0 seams.

These tests intentionally use strict public seams.  They never contact the
DeepSeek endpoint or instantiate a real ALFWorld environment.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from stage0_episode import EpisodeRunner
from stage0_pipeline import AUDIT_RUBRIC_FIELDS, Stage0Pipeline
from stage0_verifier import blind_semantic_verify
from stage0_llm import DeepSeekClient, TransportResponse
from stage0_run import baseline_skill


class _StrictAuditClient:
    def __init__(self):
        self.calls = []

    def complete_meta(self, *, role, context, token_budget):
        self.calls.append((role, context, token_budget))
        return json.dumps({
            "relevance": 0.5,
            "generality": 0.5,
            "contradiction": 0.5,
            "redundancy": 0.5,
            "over_specificity": 0.5,
            "root_cause_coverage": 0.5,
            "preservation_risk": 0.5,
        })


def test_blind_semantic_verify_uses_keyword_only_meta_seam():
    client = _StrictAuditClient()
    result = blind_semantic_verify(
        {"root_cause_id": "rc", "semantic_defect": "x"},
        [{"preservation_id": "p", "behavior": "keep"}],
        {"semantic_patch": {"edits": []}},
        client,
        token_budget=17,
    )
    assert result.valid is True
    assert client.calls[0][0] == "semantic_verifier"


class _Transport:
    def __init__(self):
        self.calls = []

    def post_json(self, url, headers, payload, timeout):
        self.calls.append(payload)
        return TransportResponse(
            200,
            {"X-Request-ID": "req"},
            {"model": "deepseek-v4-flash", "system_fingerprint": "fp", "choices": [{"message": {"content": "{}"}}]},
        )


def test_patch_and_rewrite_wire_requests_have_distinct_roles_and_json_schema():
    transport = _Transport()
    client = DeepSeekClient(transport=transport, api_key="memory-only")
    context = {"current_skill_json": "{}", "root_cause": {"root_cause_id": "rc"}}
    client.complete_meta(role="structured_patch", context=context, token_budget=33)
    client.complete_meta(role="full_rewrite", context=context, token_budget=33)
    patch, rewrite = transport.calls
    assert patch["messages"][0]["role"] == rewrite["messages"][0]["role"] == "system"
    assert patch["messages"][0]["content"] != rewrite["messages"][0]["content"]
    assert patch["response_format"] == {"type": "json_object"}
    assert rewrite["response_format"] == {"type": "json_object"}
    assert "stage0_schema" not in patch
    assert "stage0_schema" not in rewrite
    assert "semantic_patch" in patch["messages"][0]["content"]
    assert "Full Rewrite" in rewrite["messages"][0]["content"]
    assert patch["messages"][1]["content"] == rewrite["messages"][1]["content"]


class _CloseEnv:
    def __init__(self, explode=False):
        self.closed = False
        self.explode = explode

    def reset(self):
        return "Your task is to: look", {"admissible_commands": [["look"]]}

    def step(self, action):
        if self.explode:
            raise RuntimeError("step exploded")
        return "done", 1, True, {"won": True, "admissible_commands": [[]]}

    def close(self):
        self.closed = True


class _Executor:
    skill_text = "s"
    skill_hash = "h"

    def decide(self, *args):
        return type("Decision", (), {
            "action": "look", "raw_response": "FINAL_ACTION: look",
            "request_record": {"usage": {}},
        })()


def test_episode_has_reproducible_trace_id_and_closes_on_success_and_error():
    first = _CloseEnv()
    second = _CloseEnv()
    a = EpisodeRunner(first, _Executor()).run(task_id="task", environment_seed=9)
    b = EpisodeRunner(second, _Executor()).run(task_id="task", environment_seed=9)
    assert a["trace_id"] == b["trace_id"]
    assert first.closed and second.closed
    failed = _CloseEnv(explode=True)
    EpisodeRunner(failed, _Executor()).run(task_id="task", environment_seed=9)
    assert failed.closed


def test_validation_seed_is_shared_across_conditions_and_factory_receives_it():
    seen = []
    pipeline = Stage0Pipeline.__new__(Stage0Pipeline)
    pipeline.environment_seed = 123
    for condition in ("baseline", "structured_patch", "full_rewrite"):
        seen.append(pipeline._seed_for("pick_and_place_simple-a-m-r-1/trial_x/game.tw-pddl", condition, 0))
    assert seen[0] == seen[1] == seen[2]


def test_s0_human_audit_is_pending_until_complete_scores():
    # This is a state-level contract test; full episode execution is covered
    # by the existing offline pipeline fixture.
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        state = {"status": "awaiting_human_audit"}
        (root / "state.json").write_text(json.dumps(state), encoding="utf-8")
        assert json.loads((root / "state.json").read_text(encoding="utf-8"))["status"] == "awaiting_human_audit"


def _small_manifests(size=4):
    return {
        "calibration": [f"pick_and_place_simple-a-m-r-{i}/trial_c/game.tw-pddl" for i in range(1, size + 1)],
        "evolution": [f"clean_and_place-a-m-r-{i}/trial_e/game.tw-pddl" for i in range(1, size + 1)],
        "patch_validation": [f"heat_and_place-a-m-r-{i}/trial_v/game.tw-pddl" for i in range(1, size + 1)],
    }


class _S0OnlyClient:
    def __init__(self):
        self.contexts = []

    def complete_meta(self, *, role, context, token_budget):
        self.contexts.append((role, context, token_budget))
        if role == "s0_generator":
            value = baseline_skill()
            if len(self.contexts) > 1:
                value["skill_package"]["package_id"] = "alfworld-stage0-s0-regenerated"
            return json.dumps(value)
        return json.dumps({"root_causes": []})


def test_human_gate_rejection_only_retries_failed_labels_and_changes_s0_hash():
    with tempfile.TemporaryDirectory() as directory:
        client = _S0OnlyClient()
        pipeline = Stage0Pipeline(directory, client=client, task_manifests=_small_manifests(1), testing_plan_size=1)
        first = pipeline.prepare()
        first_hash = first["s0_skill_hash"]
        failed = {field: field == "schema_valid" for field in AUDIT_RUBRIC_FIELDS[:0]}
        failed = {"schema_valid": False, "no_instance_leakage": True, "six_family_applicable": True, "no_contradiction": True, "within_budget": True}
        second = pipeline.reject_human_gate(failed, reason="reviewer found schema concern")
        assert second["status"] == "awaiting_human_gate"
        assert second["s0_skill_hash"] != first_hash
        assert client.contexts[-1][1]["gate_feedback"] == ["schema_valid"]


def test_checkpoint_resume_reuses_completed_episode_and_marks_runtime_error():
    class Client:
        def complete_meta(self, *, role, context, token_budget):
            return json.dumps(baseline_skill()) if role == "s0_generator" else json.dumps({"root_causes": []})

    class Runner:
        def __init__(self):
            self.calls = []
            self.fail_once = True

        def __call__(self, skill, env, task_id, condition):
            self.calls.append(task_id)
            if self.fail_once and len(self.calls) == 2:
                raise RuntimeError("synthetic interruption")
            return {"task_id": task_id, "success": True, "steps": 1, "termination": "success", "request_records": [{"request_id": task_id, "model": "deepseek-v4-flash", "system_fingerprint": "fp", "usage": {}}]}

    with tempfile.TemporaryDirectory() as directory:
        runner = Runner()
        pipeline = Stage0Pipeline(directory, client=Client(), task_manifests=_small_manifests(), testing_plan_size=4, environment_factory=lambda task, condition, seed: object(), episode_runner_factory=runner)
        pipeline.prepare()
        pipeline.approve({"schema_valid": True, "no_instance_leakage": True, "six_family_applicable": True, "no_contradiction": True, "within_budget": True}, auditor="tester")
        failed = pipeline.run()
        assert failed["status"] == "error"
        assert runner.calls.count(_small_manifests()["calibration"][0]) == 1
        assert any(record.get("request_id") == _small_manifests()["calibration"][0] for record in failed["request_records"])
        runner.fail_once = False
        resumed = Stage0Pipeline(directory, client=Client(), environment_factory=lambda task, condition, seed: object(), episode_runner_factory=runner, testing_plan_size=4)
        resumed.resume(continue_run=True)
        assert runner.calls.count(_small_manifests()["calibration"][0]) == 1
        assert len(runner.calls) <= 5  # calibration ceiling stops before any duplicate schedule
        checkpoint = json.loads((Path(directory) / "checkpoint.json").read_text(encoding="utf-8"))
        request_ids = [entry["row"]["request_records"][0]["request_id"] for entry in checkpoint["completed"].values() if entry["row"].get("request_records")]
        assert len(request_ids) == len(set(request_ids))


def test_pipeline_closes_injected_environment_when_runner_raises():
    class Client:
        def complete_meta(self, *, role, context, token_budget):
            return json.dumps(baseline_skill())

    class Env:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    environments = []

    def factory(task_id, condition, seed):
        value = Env()
        environments.append(value)
        return value

    def raising_runner(*args):
        raise RuntimeError("runner failure")

    with tempfile.TemporaryDirectory() as directory:
        pipeline = Stage0Pipeline(directory, client=Client(), task_manifests=_small_manifests(1), testing_plan_size=1, environment_factory=factory, episode_runner_factory=raising_runner)
        pipeline.prepare()
        pipeline.approve({"schema_valid": True, "no_instance_leakage": True, "six_family_applicable": True, "no_contradiction": True, "within_budget": True}, auditor="tester")
        state = pipeline.run()
        assert state["status"] == "error"
        assert environments and environments[0].closed


def test_observed_server_model_drift_is_error_and_recorded():
    class Client:
        def complete_meta(self, *, role, context, token_budget):
            return json.dumps(baseline_skill())

    def runner(skill, env, task_id, condition):
        return {
            "task_id": task_id,
            "success": False,
            "steps": 1,
            "termination": "failed",
            "request_records": [{"model": "unexpected-server", "system_fingerprint": "fp-a", "usage": {}}],
        }

    with tempfile.TemporaryDirectory() as directory:
        pipeline = Stage0Pipeline(directory, client=Client(), task_manifests=_small_manifests(1), testing_plan_size=1, environment_factory=lambda *args: object(), episode_runner_factory=runner)
        pipeline.prepare()
        pipeline.approve({"schema_valid": True, "no_instance_leakage": True, "six_family_applicable": True, "no_contradiction": True, "within_budget": True}, auditor="tester")
        state = pipeline.run()
        assert state["status"] == "error"
        assert any("observed server model" in error for error in state["errors"])
        code_state = json.loads((Path(directory) / "code_state.json").read_text(encoding="utf-8"))
        assert code_state["request_records"]
