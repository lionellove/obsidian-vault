"""Public state-machine and offline orchestration behavior."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from stage0_core import canonical
from stage0_pipeline import Stage0Pipeline, Stage0ArtifactLayout
from stage0_run import baseline_skill


def _manifests():
    return {
        "calibration": ["pick_and_place_simple-a-m-r-1/trial_c/game.tw-pddl", "clean_and_place-a-m-r-2/trial_c/game.tw-pddl", "heat_and_place-a-m-r-3/trial_c/game.tw-pddl"],
        "evolution": ["cool_and_place-a-m-r-4/trial_e/game.tw-pddl", "pick_two_obj_and_place-a-m-r-5/trial_e/game.tw-pddl", "look_at_obj_in_light-a-m-r-6/trial_e/game.tw-pddl"],
        "patch_validation": ["pick_and_place_simple-b-m-r-7/trial_v/game.tw-pddl", "clean_and_place-b-m-r-8/trial_v/game.tw-pddl", "heat_and_place-b-m-r-9/trial_v/game.tw-pddl"],
    }


class FakeClient:
    def __init__(self):
        self.calls = []

    def complete_meta(self, role, context, token_budget):
        self.calls.append((role, context, token_budget))
        if role == "s0_generator":
            return json.dumps(baseline_skill())
        # The pipeline state tests stop before semantic evolution; these
        # responses keep the injected seam usable if run is requested.
        return json.dumps({"root_causes": []})


def _episode_runner(skill, env, task_id, condition):
    return {"task_id": task_id, "condition": condition, "success": condition == "baseline", "steps": 1, "termination": "won" if condition == "baseline" else "failed", "request_records": []}


def test_prepare_pauses_for_human_gate_and_approve_freezes_hashes():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        pipeline = Stage0Pipeline(
            root,
            client=FakeClient(),
            task_manifests=_manifests(),
            testing_plan_size=3,
            episode_runner_factory=_episode_runner,
        )
        prepared = pipeline.prepare()
        assert prepared["status"] == "awaiting_human_gate"
        assert (root / "state.json").exists()
        assert (root / "manifests" / "calibration.json").exists()
        approved = pipeline.approve(
            {"schema_valid": True, "no_instance_leakage": True, "six_family_applicable": True, "no_contradiction": True, "within_budget": True},
            auditor="tester",
            timestamp="2026-08-25T00:00:00Z",
        )
        assert approved["status"] == "approved"
        assert (root / "s0" / "skill_package.sha256").exists()
        assert pipeline.status()["status"] == "approved"


def test_resume_fails_closed_when_frozen_hash_changes():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        pipeline = Stage0Pipeline(root, client=FakeClient(), task_manifests=_manifests(), testing_plan_size=3)
        pipeline.prepare()
        pipeline.approve({"schema_valid": True, "no_instance_leakage": True, "six_family_applicable": True, "no_contradiction": True, "within_budget": True}, auditor="tester", timestamp="now")
        (root / "s0" / "rendered_skill.md").write_text("tampered", encoding="utf-8")
        try:
            pipeline.resume()
        except RuntimeError as exc:
            assert "hash" in str(exc).lower()
        else:
            raise AssertionError("resume accepted a modified frozen artifact")


def test_artifact_layout_has_plan_directories_and_hash_sidecars():
    with tempfile.TemporaryDirectory() as directory:
        layout = Stage0ArtifactLayout(Path(directory))
        paths = layout.create()
        for relative in ("manifests", "s0", "trajectories/calibration", "trajectories/evolution", "trajectories/validation", "ir", "candidates/structured_patch", "candidates/full_rewrite", "verifier", "audit", "report"):
            assert (Path(directory) / relative).is_dir()
        assert paths["root"] == Path(directory)


def test_production_validation_schedule_has_each_permutation_exactly_three_times():
    pipeline = Stage0Pipeline.__new__(Stage0Pipeline)
    task_ids = [f"pick_and_place_simple-a-m-r-{index}/trial_{index}/game.tw-pddl" for index in range(18)]
    schedule = pipeline.validation_schedule(task_ids)
    orders = [tuple(item["condition_order"]) for item in schedule]
    from collections import Counter
    assert len(schedule) == 18
    assert set(Counter(orders).values()) == {3}


class FullFakeClient:
    def __init__(self):
        self.calls = []

    def complete_meta(self, role, context, token_budget):
        self.calls.append((role, context, token_budget))
        if role == "s0_generator":
            return json.dumps(baseline_skill())
        if role == "failure_analyzer":
            trace_id = context["trace_id"]
            return json.dumps({
                "failure_id": f"failure-{trace_id}", "trace_id": trace_id, "task_id": context["task_id"],
                "defect_type": "missing_state_confirmation", "location": {"trajectory_steps": [1], "related_skill_ids": ["parse_goal"]},
                "scope": {"level": "task_family", "target": "pick_and_place"},
                "evidence": {"observation": "not verified", "expected_semantics": "verify state"},
                "cause": "verification is omitted", "patchability": "skill_patchable", "confidence": 0.9,
            })
        if role == "success_analyzer":
            return json.dumps({
                "preservation_id": "preserve-success", "trace_id": context["trace_id"], "task_id": context["task_id"],
                "behavior": "verify before completion", "scope": {"level": "task_family", "target": "pick_and_place"},
                "supported_by": [{"trace_id": context["trace_id"], "trajectory_steps": [1]}], "related_skill_ids": ["verify_goal"], "confidence": 0.8,
            })
        if role == "root_cause_merger":
            refs = [{"failure_id": row["failure_id"], "trace_id": row["trace_id"], "task_id": row["task_id"], "trajectory_steps": [1]} for row in context["failures"]]
            return json.dumps({"root_causes": [{"root_cause_id": "rc-verify", "semantic_defect": "verification is omitted", "scope": {"level": "task_family", "target": "pick_and_place"}, "supported_by": refs, "contradictory_evidence": [], "patchability": "skill_patchable", "priority": 1}]})
        if role in ("structured_patch", "full_rewrite"):
            skill = json.loads(context["current_skill_json"])
            if role == "structured_patch":
                return json.dumps({"semantic_patch": {"diagnosis_binding": {"root_cause_id": "rc-verify"}, "edits": [{"op": "ADD", "kind": "CONSTRAINT", "target_id": "c-verify", "value": {"id": "c-verify", "rule": "Verify state.", "scope": {"level": "task_family", "target": "pick_and_place"}}, "addresses": ["rc-verify"]}]}})
            skill["skill_package"]["constraints"] = [{"id": "c-verify", "rule": "Verify state.", "scope": {"level": "task_family", "target": "pick_and_place"}}]
            return json.dumps({"full_rewrite": {"diagnosis_binding": {"root_cause_id": "rc-verify"}, "rewritten_skill_package": skill["skill_package"], "change_manifest": [{"change": "ADD", "kind": "CONSTRAINT", "target_id": "c-verify", "addresses": ["rc-verify"]}]}})
        if role == "semantic_verifier":
            return json.dumps({field: 0.8 for field in ("relevance", "generality", "contradiction", "redundancy", "over_specificity", "root_cause_coverage", "preservation_risk")})
        raise AssertionError(role)


def test_fake_pipeline_runs_calibration_evolution_and_dynamic_go_gate():
    def runner(skill, env, task_id, condition):
        if "trial_c" in task_id:
            success = task_id.endswith("-1/trial_c/game.tw-pddl")
        elif "trial_e" in task_id:
            success = task_id.endswith("-4/trial_e/game.tw-pddl")
        elif condition == "baseline":
            success = task_id.endswith("-9/trial_v/game.tw-pddl")
        else:
            success = True
        return {"task_id": task_id, "trace_id": "trace-" + task_id.split("/")[0], "success": success, "steps": 1, "termination": "won" if success else "failed", "request_records": []}

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        client = FullFakeClient()
        pipeline = Stage0Pipeline(root, client=client, task_manifests=_manifests(), testing_plan_size=3, environment_factory=lambda task, condition, seed: object(), episode_runner_factory=runner)
        pipeline.prepare()
        pipeline.approve({"schema_valid": True, "no_instance_leakage": True, "six_family_applicable": True, "no_contradiction": True, "within_budget": True}, auditor="tester", timestamp="now")
        state = pipeline.run()
        assert state["status"] == "completed"
        assert state["stage0_gate"]["go"] is True
        assert (root / "report" / "metrics.json").exists()
        assert (root / "audit" / "blinded_packet.json").exists()
        packet_text = (root / "audit" / "blinded_packet.json").read_text(encoding="utf-8").lower()
        assert "semantic_patch" not in packet_text
        assert "full_rewrite" not in packet_text
        assert '"validation_score":' not in packet_text
        assert any(role == "structured_patch" for role, _, _ in client.calls)
        assert any(role == "full_rewrite" for role, _, _ in client.calls)
