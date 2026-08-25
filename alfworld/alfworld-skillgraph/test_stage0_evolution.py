"""Offline integration tests for the public EvolutionEngine seam."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from stage0_evolution import EvolutionEngine, FailureAnalyzer, RootCauseMerger, SuccessAnalyzer
from stage0_artifacts import ArtifactWriter


def _skill():
    nodes = [
        {
            "id": f"node-{index}",
            "type": "action" if index < 5 else "terminal",
            "instruction": f"Perform step {index}.",
            "scope": {"level": "task_family", "target": "pick_and_place"},
        }
        for index in range(6)
    ]
    return {
        "skill_package": {
            "schema_version": "0.1",
            "package_id": "baseline",
            "entry_node": "node-0",
            "nodes": nodes,
            "edges": [
                {"id": f"edge-{i}", "source": f"node-{i}", "target": f"node-{i+1}", "condition": "continue"}
                for i in range(5)
            ],
            "constraints": [],
            "verifications": [],
            "fallbacks": [],
        }
    }


def _failure(failure_id, trace_id, task_id):
    return {
        "trace_id": trace_id,
        "task_id": task_id,
        "success": False,
        "trajectory": [{"observation": "placed", "action": "stop"}],
        "task_goal": "put the apple in the mug",
        "admissible_actions": ["stop"],
        "reward": 0,
        "termination": "failed",
        "failure_id_hint": failure_id,
    }


def _success():
    return {
        "trace_id": "trace-success",
        "task_id": "pick_and_place_simple-apple-mug-table-1/trial_3/game.tw-pddl",
        "success": True,
        "trajectory": [{"observation": "verified", "action": "stop"}],
        "task_goal": "put the apple in the mug",
        "admissible_actions": ["stop"],
        "reward": 1,
        "termination": "success",
    }


class FakeClient:
    def __init__(self, *, no_root=False, no_patch=False, invalid=False):
        self.calls = []
        self.no_root = no_root
        self.no_patch = no_patch
        self.invalid = invalid

    def complete_meta(self, role, context, token_budget):
        self.calls.append((role, context, token_budget))
        if role == "failure_analyzer":
            return json.dumps({
                "failure_id": context["failure_id_hint"],
                "trace_id": context["trace_id"],
                "task_id": context["task_id"],
                "defect_type": "missing_state_confirmation",
                "location": {"trajectory_steps": [1], "related_skill_ids": ["node-5"]},
                "scope": {"level": "task_family", "target": "pick_and_place"},
                "evidence": {"trace_id": context["trace_id"], "trajectory_steps": [1], "observation": "placed", "expected_semantics": "verify"},
                "cause": "verification is omitted",
                "patchability": "skill_patchable",
                "confidence": 0.9,
            })
        if role == "success_analyzer":
            return json.dumps({
                "preservation_id": "preserve-success",
                "trace_id": context["trace_id"],
                "task_id": context["task_id"],
                "behavior": "verify before completion",
                "scope": {"level": "task_family", "target": "pick_and_place"},
                "supported_by": [{"trace_id": context["trace_id"], "trajectory_steps": [1]}],
                "related_skill_ids": ["node-5"],
                "confidence": 0.8,
            })
        if role == "root_cause_merger":
            if self.no_root:
                return json.dumps({"root_causes": []})
            return json.dumps({"root_causes": [{
                "root_cause_id": "rc-verify",
                "semantic_defect": "verification is omitted",
                "scope": {"level": "task_family", "target": "pick_and_place"},
                "supported_by": [
                    {"failure_id": "failure-1", "trace_id": "trace-1", "task_id": "task-1", "trajectory_steps": [1]},
                    {"failure_id": "failure-2", "trace_id": "trace-2", "task_id": "task-2", "trajectory_steps": [1]},
                ],
                "contradictory_evidence": [], "patchability": "skill_patchable", "priority": 1, "confidence": 0.9,
            }]})
        if role in ("structured_patch", "full_rewrite"):
            if self.no_patch:
                return json.dumps({"status": "NO_PATCH", "reason": "not patchable"})
            if self.invalid:
                return json.dumps({"semantic_patch": {"diagnosis_binding": {"root_cause_id": "wrong"}, "edits": []}})
            if role == "structured_patch":
                return json.dumps({"semantic_patch": {"diagnosis_binding": {"root_cause_id": "rc-verify"}, "edits": [{"op": "ADD", "kind": "CONSTRAINT", "target_id": "constraint-verify", "value": {"id": "constraint-verify", "rule": "Verify destination.", "scope": {"level": "task_family", "target": "pick_and_place"}}, "addresses": ["rc-verify"]}]}})
            package = json.loads(context["current_skill_json"])["skill_package"]
            package["constraints"] = [{"id": "constraint-verify", "rule": "Verify destination.", "scope": {"level": "task_family", "target": "pick_and_place"}}]
            return json.dumps({"full_rewrite": {"diagnosis_binding": {"root_cause_id": "rc-verify"}, "rewritten_skill_package": package, "change_manifest": [{"change": "ADD", "kind": "CONSTRAINT", "target_id": "constraint-verify", "addresses": ["rc-verify"]}]}})
        if role == "semantic_verifier":
            return json.dumps({"relevance": 0.2, "generality": 0.8, "contradiction": 0.1, "redundancy": 0.1, "over_specificity": 0.2, "root_cause_coverage": 0.9, "preservation_risk": 0.1})
        raise AssertionError(role)


def test_fake_evolution_engine_generates_two_checked_candidates_and_artifacts():
    client = FakeClient()
    trajectories = [_failure("failure-1", "trace-1", "task-1"), _failure("failure-2", "trace-2", "task-2"), _success()]
    result = EvolutionEngine(client, token_budget=321).run(trajectories, _skill())
    assert result.root_cause["root_cause_id"] == "rc-verify"
    assert result.structured_candidate.status == "VALID"
    assert result.rewrite_candidate.status == "VALID"
    assert result.structured_verifier.eligible_for_dynamic_validation is True
    assert result.rewrite_verifier.eligible_for_dynamic_validation is True
    generator_calls = [x for x in client.calls if x[0] in ("structured_patch", "full_rewrite")]
    assert len(generator_calls) == 2
    assert generator_calls[0][2] == generator_calls[1][2] == 321
    assert generator_calls[0][1]["current_skill_json"] == generator_calls[1][1]["current_skill_json"]
    for _, context, _ in generator_calls:
        assert '"trajectory":' not in json.dumps(context)
        assert "expert_plan" not in json.dumps(context)
        assert "pddl" not in json.dumps(context).lower()
    with tempfile.TemporaryDirectory() as directory:
        tmp_path = Path(directory)
        paths = ArtifactWriter(tmp_path).write(result)
        assert paths
        assert any("structured_patch" in str(path) for path in paths.values())
        assert list((tmp_path / "candidates" / "structured_patch").glob("*.sha256"))
        assert not any("api_key" in path.read_text(encoding="utf-8") for path in tmp_path.rglob("*.json"))


def test_no_qualified_root_cause_skips_both_generators():
    client = FakeClient(no_root=True)
    result = EvolutionEngine(client).run([_failure("failure-1", "trace-1", "task-1"), _success()], _skill())
    assert result.root_cause["status"] == "NO_ROOT_CAUSE"
    assert result.structured_candidate is None
    assert not [role for role, _, _ in client.calls if role in ("structured_patch", "full_rewrite")]


def test_no_patch_and_invalid_candidate_are_fail_closed_and_semantic_audit_has_no_veto():
    no_patch_client = FakeClient(no_patch=True)
    no_patch = EvolutionEngine(no_patch_client).run([_failure("failure-1", "trace-1", "task-1"), _failure("failure-2", "trace-2", "task-2")], _skill())
    assert no_patch.structured_candidate.status == "NO_PATCH"
    assert no_patch.rewrite_candidate.status == "NO_PATCH"

    invalid_client = FakeClient(invalid=True)
    invalid = EvolutionEngine(invalid_client).run([_failure("failure-1", "trace-1", "task-1"), _failure("failure-2", "trace-2", "task-2")], _skill())
    assert invalid.structured_candidate.status == "INVALID"
    assert invalid.rewrite_candidate.status == "INVALID"


def test_public_analyzer_and_merger_seams_reject_hidden_fields():
    client = FakeClient()
    trajectory = _failure("failure-1", "trace-1", "task-1")
    failure = FailureAnalyzer(client).analyze(trajectory, _skill())
    preservation = SuccessAnalyzer(client).analyze(_success(), _skill())
    assert failure["failure_id"] == "failure-1"
    assert preservation["preservation_id"] == "preserve-success"
    selected = RootCauseMerger(client).merge(
        [
            dict(failure, trace_id="trace-1", task_id="task-1"),
            dict(failure, failure_id="failure-2", trace_id="trace-2", task_id="task-2"),
        ],
        [preservation],
    )
    assert selected["root_cause_id"] == "rc-verify"
    bad = dict(trajectory, expert_plan=["do not pass this"])
    try:
        FailureAnalyzer(client).analyze(bad, _skill())
    except ValueError:
        pass
    else:
        raise AssertionError("FailureAnalyzer accepted hidden expert state")
