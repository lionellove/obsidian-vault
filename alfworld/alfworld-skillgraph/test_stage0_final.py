"""Final blocking regressions A-E; stdlib-only red/green tests."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import stage0_pipeline
from stage0_core import sha256_file
from stage0_metrics import estimate_api_cost
from stage0_pipeline import AUDIT_RUBRIC_FIELDS, Stage0Pipeline
from stage0_run import baseline_skill
from stage0_verifier import CandidateResult
from stage0_evolution import EvolutionResult
import stage0_cli


def _manifests(size=4):
    return {
        "calibration": [f"pick_and_place_simple-a-m-r-{i}/trial_c/game.tw-pddl" for i in range(1, size + 1)],
        "evolution": [f"clean_and_place-a-m-r-{i}/trial_e/game.tw-pddl" for i in range(1, size + 1)],
        "patch_validation": [f"heat_and_place-a-m-r-{i}/trial_v/game.tw-pddl" for i in range(1, size + 1)],
    }


class _Client:
    def complete_meta(self, *, role, context, token_budget):
        return json.dumps(baseline_skill()) if role == "s0_generator" else json.dumps({"root_causes": []})


class _Runner:
    def __init__(self, fail_on=None, success_count=None):
        self.calls = []
        self.fail_on = fail_on
        self.success_count = success_count

    def __call__(self, skill, env, task_id, condition):
        self.calls.append(task_id)
        if self.fail_on is not None and len(self.calls) == self.fail_on:
            raise RuntimeError("simulated crash")
        return {
            "task_id": task_id,
            "success": self.success_count is None or len(self.calls) <= self.success_count,
            "steps": 1,
            "termination": "success",
            "request_records": [],
        }


def test_cost_estimate_uses_exact_base_rates_without_double_counting_reasoning():
    result = estimate_api_cost([
        {"usage": {"prompt_tokens": 100, "cache_hit_tokens": 10, "cache_miss_tokens": 90, "reasoning_tokens": 7, "output_tokens": 20}},
    ], captured_at="2026-08-25T00:00:00Z")
    expected = 10 / 1_000_000 * 0.0028 + 90 / 1_000_000 * 0.14 + 20 / 1_000_000 * 0.28
    assert result["status"] == "complete"
    assert abs(result["estimated_api_cost_usd"] - expected) < 1e-15
    assert result["usage"]["reasoning_tokens"] == 7
    assert result["pricing"]["source"].startswith("https://api-docs.deepseek.com/")


def test_cost_missing_billing_usage_is_incomplete():
    result = estimate_api_cost([{"usage": {"output_tokens": 4}}])
    assert result["status"] == "incomplete"
    assert result["estimated_api_cost_usd"] is None


def test_state_write_uses_atomic_replace_and_preserves_previous_bytes_on_crash():
    with tempfile.TemporaryDirectory() as directory:
        pipeline = Stage0Pipeline(
            directory,
            client=_Client(),
            task_manifests=_manifests(1),
            testing_plan_size=1,
        )
        pipeline.layout.create()
        atomic_calls = []
        original_atomic = pipeline.layout.write_json_atomic

        def record_atomic(relative, value):
            atomic_calls.append(str(relative))
            return original_atomic(relative, value)

        def non_atomic_forbidden(*args, **kwargs):
            raise AssertionError("state writes must use write_json_atomic")

        pipeline.layout.write_json_atomic = record_atomic
        pipeline.layout.write_json = non_atomic_forbidden
        old_state = {"status": "running", "generation": 1}
        pipeline._write_state(old_state)
        state_path = Path(directory) / "state.json"
        old_bytes = state_path.read_bytes()
        old_sidecar = state_path.with_name("state.sha256").read_text(encoding="ascii")

        original_replace = stage0_pipeline.os.replace

        def crash_before_replace(source, target):
            raise OSError("simulated crash before state replacement")

        stage0_pipeline.os.replace = crash_before_replace
        try:
            try:
                pipeline._write_state({"status": "running", "generation": 2})
            except OSError as exc:
                assert "simulated crash" in str(exc)
            else:
                raise AssertionError("state write unexpectedly succeeded after simulated crash")
        finally:
            stage0_pipeline.os.replace = original_replace

        assert atomic_calls == ["state.json", "state.json"]
        assert state_path.read_bytes() == old_bytes
        assert state_path.with_name("state.sha256").read_text(encoding="ascii") == old_sidecar
        assert pipeline.status()["generation"] == 1


def test_status_fails_closed_with_clear_error_for_truncated_state():
    with tempfile.TemporaryDirectory() as directory:
        pipeline = Stage0Pipeline(
            directory,
            client=_Client(),
            task_manifests=_manifests(1),
            testing_plan_size=1,
        )
        pipeline.layout.create()
        (Path(directory) / "state.json").write_text('{"status":"running"', encoding="utf-8")

        try:
            pipeline.status()
        except RuntimeError as exc:
            message = str(exc).casefold()
            assert "state.json" in message
            assert "invalid" in message or "corrupt" in message or "unreadable" in message
        else:
            raise AssertionError("truncated state must fail closed")


def test_checkpoint_journal_wins_when_state_is_stale_after_simulated_crash():
    with tempfile.TemporaryDirectory() as directory:
        runner = _Runner(fail_on=2)
        pipeline = Stage0Pipeline(
            directory,
            client=_Client(),
            task_manifests=_manifests(),
            testing_plan_size=4,
            environment_factory=lambda *args: object(),
            episode_runner_factory=runner,
        )
        pipeline.prepare()
        approved = pipeline.approve({field: True for field in ("schema_valid", "no_instance_leakage", "six_family_applicable", "no_contradiction", "within_budget")}, auditor="tester")
        stale_state = json.loads((Path(directory) / "state.json").read_text(encoding="utf-8"))
        assert approved["status"] == "approved"
        assert pipeline.run()["status"] == "error"
        journal = json.loads((Path(directory) / "checkpoint.json").read_text(encoding="utf-8"))
        assert journal["generation"] >= 1
        # Simulate crash between journal replace and state write: restore the
        # old state while leaving the authoritative journal intact.
        (Path(directory) / "state.json").write_text(json.dumps(stale_state, sort_keys=True), encoding="utf-8")
        runner.fail_on = None
        resumed = Stage0Pipeline(
            directory,
            client=_Client(),
            environment_factory=lambda *args: object(),
            episode_runner_factory=runner,
            testing_plan_size=4,
        )
        resumed.resume(continue_run=True)
        assert runner.calls.count(_manifests()["calibration"][0]) == 1
        assert len(runner.calls) <= 5


def test_tampered_evolution_result_is_rejected_by_exact_sidecar_hash():
    with tempfile.TemporaryDirectory() as directory:
        runner = _Runner(success_count=2)
        pipeline = Stage0Pipeline(directory, client=_Client(), task_manifests=_manifests(), testing_plan_size=4, environment_factory=lambda *args: object(), episode_runner_factory=runner)
        pipeline.prepare()
        pipeline.approve({field: True for field in ("schema_valid", "no_instance_leakage", "six_family_applicable", "no_contradiction", "within_budget")}, auditor="tester")
        # Reach a runtime state with a frozen evolution artifact.
        pipeline.run()
        path = Path(directory) / "ir" / "evolution_result.json"
        if path.exists():
            path.write_text(path.read_text(encoding="utf-8") + "\n tampered", encoding="utf-8")
            state = json.loads((Path(directory) / "state.json").read_text(encoding="utf-8"))
            state["status"] = "error"
            (Path(directory) / "state.json").write_text(json.dumps(state), encoding="utf-8")
            resumed = Stage0Pipeline(directory, client=_Client(), environment_factory=lambda *args: object(), episode_runner_factory=runner, testing_plan_size=4).resume(continue_run=True)
            assert resumed["status"] == "error"
            assert any("evolution" in error.casefold() or "hash" in error.casefold() for error in resumed["errors"])


def test_blind_packet_uses_anonymous_uniform_envelopes_and_private_mapping():
    with tempfile.TemporaryDirectory() as directory:
        pipeline = Stage0Pipeline(directory, client=_Client(), task_manifests=_manifests(1), testing_plan_size=1)
        pipeline.layout.create()
        pipeline.layout.write_json("s0/skill_package.json", baseline_skill())
        patch = CandidateResult(
            method="structured_patch", status="VALID", raw_response="{}", final_ir={"semantic_patch": {}},
            structural_result={"valid": True, "skill": baseline_skill(), "diff": []}, eligible_for_dynamic_validation=True,
        )
        rewrite = CandidateResult(
            method="full_rewrite", status="VALID", raw_response="{}", final_ir={"full_rewrite": {}},
            structural_result={"valid": True, "skill": baseline_skill(), "diff": []}, eligible_for_dynamic_validation=True,
        )
        result = EvolutionResult(structured_candidate=patch, rewrite_candidate=rewrite)
        pipeline._write_audit_packet(result)
        packet = json.loads((Path(directory) / "audit" / "blinded_packet.json").read_text(encoding="utf-8"))
        mapping = Path(directory) / "audit" / "private_candidate_mapping.json"
        assert mapping.exists()
        assert len(packet["candidates"]) == 2
        assert {tuple(sorted(candidate)) for candidate in packet["candidates"]} == {
            ("candidate_id", "candidate_semantics", "evidence_refs", "final_skill_package", "semantic_changes"),
        }
        text = json.dumps(packet, ensure_ascii=False).casefold()
        for token in ("structured", "patch", "rewrite", "full_rewrite", "method", "validation_score", "edits", "candidate_skill_package"):
            assert token not in text

        orders = set()
        for seed in range(1, 8):
            with tempfile.TemporaryDirectory() as other:
                variant = Stage0Pipeline(other, client=_Client(), task_manifests=_manifests(1), testing_plan_size=1, environment_seed=seed)
                variant.layout.create()
                variant.layout.write_json("s0/skill_package.json", baseline_skill())
                variant._write_audit_packet(result, baseline_skill())
                private = json.loads((Path(other) / "audit" / "private_candidate_mapping.json").read_text(encoding="utf-8"))
                orders.add(tuple(private.values()))
        assert len(orders) > 1


def test_cli_reject_s0_requires_key_before_any_generation():
    with tempfile.TemporaryDirectory() as directory:
        run_dir = Path(directory) / "run"
        checklist = Path(directory) / "checklist.json"
        checklist.write_text(json.dumps({"schema_valid": False}), encoding="utf-8")
        old_key = os.environ.pop("DEEPSEEK_API_KEY", None)
        try:
            assert stage0_cli.main(["reject-s0", "--run-dir", str(run_dir), "--checklist", str(checklist)]) != 0
        finally:
            if old_key is not None:
                os.environ["DEEPSEEK_API_KEY"] = old_key


def test_cli_reject_s0_rebuilds_frozen_state_and_forwards_only_false_labels():
    class FakeClient:
        contexts = []

        def __init__(self, *args, **kwargs):
            pass

        def complete_meta(self, *, role, context, token_budget):
            self.contexts.append((role, context, token_budget))
            return json.dumps(baseline_skill())

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        train = root / "json_2.1.1" / "train"
        train.mkdir(parents=True)
        run_dir = root / "run"
        pipeline = Stage0Pipeline(run_dir, client=FakeClient(), data_root=train, task_manifests=_manifests(1), testing_plan_size=1)
        pipeline.prepare()
        checklist_path = root / "checklist.json"
        checklist_path.write_text(json.dumps({"schema_valid": False, "no_instance_leakage": True, "six_family_applicable": True, "no_contradiction": True, "within_budget": True}), encoding="utf-8")
        old_key = os.environ.get("DEEPSEEK_API_KEY")
        old_client = stage0_cli.DeepSeekClient
        os.environ["DEEPSEEK_API_KEY"] = "test-key-not-written"
        stage0_cli.DeepSeekClient = FakeClient
        try:
            assert stage0_cli.main(["reject-s0", "--run-dir", str(run_dir), "--data-root", str(train), "--checklist", str(checklist_path), "--reason", "schema"] ) == 0
        finally:
            stage0_cli.DeepSeekClient = old_client
            if old_key is None:
                os.environ.pop("DEEPSEEK_API_KEY", None)
            else:
                os.environ["DEEPSEEK_API_KEY"] = old_key
        state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
        assert state["status"] == "awaiting_human_gate"
        assert FakeClient.contexts[-1][1]["gate_feedback"] == ["schema_valid"]
