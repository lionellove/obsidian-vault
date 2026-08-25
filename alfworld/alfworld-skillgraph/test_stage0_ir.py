"""Public behavior tests for the representation-neutral Stage 0 IR."""

from __future__ import annotations

from stage0_ir import (
    IRValidationError,
    normalize_failure_ir,
    normalize_preservation_ir,
    normalize_root_cause_ir,
    validate_failure_ir,
    validate_preservation_ir,
    validate_root_cause_ir,
)


def _failure(**overrides):
    value = {
        "failure_id": "failure-1",
        "trace_id": "trace-1",
        "task_id": "pick_and_place_simple-apple-mug-table-1/trial_1/game.tw-pddl",
        "defect_type": "missing_state_confirmation",
        "location": {"trajectory_steps": [2], "related_skill_ids": ["verify-placement"]},
        "scope": {"level": "task_family", "target": "pick_and_place"},
        "evidence": {
            "trace_id": "trace-1",
            "trajectory_steps": [2],
            "observation": "The object was placed without checking the receptacle.",
            "expected_semantics": "Verify the placement before finishing.",
        },
        "cause": "The workflow omits a placement verification.",
        "patchability": "skill_patchable",
        "confidence": 0.9,
    }
    value.update(overrides)
    return value


def _preservation(**overrides):
    value = {
        "preservation_id": "preserve-1",
        "trace_id": "success-trace-1",
        "task_id": "pick_and_place_simple-apple-mug-table-1/trial_2/game.tw-pddl",
        "behavior": "Keep checking the destination before declaring success.",
        "scope": {"level": "task_family", "target": "pick_and_place"},
        "supported_by": [{"trace_id": "success-trace-1", "trajectory_steps": [3]}],
        "related_skill_ids": ["verify-placement"],
        "confidence": 0.8,
    }
    value.update(overrides)
    return value


def _root(**overrides):
    value = {
        "root_cause_id": "rc-verify",
        "semantic_defect": "Placement is not verified before completion.",
        "scope": {"level": "task_family", "target": "pick_and_place"},
        "supported_by": [
            {"failure_id": "failure-1", "trace_id": "trace-1", "task_id": "task-1", "trajectory_steps": [2]},
            {"failure_id": "failure-2", "trace_id": "trace-2", "task_id": "task-2", "trajectory_steps": [4]},
        ],
        "contradictory_evidence": [],
        "patchability": "skill_patchable",
        "priority": 1,
        "confidence": 0.9,
    }
    value.update(overrides)
    return value


def test_valid_ir_is_normalized_deterministically():
    failure = normalize_failure_ir(_failure())
    preservation = normalize_preservation_ir(_preservation())
    root = normalize_root_cause_ir(_root())
    assert failure["failure_id"] == "failure-1"
    assert preservation["preservation_id"] == "preserve-1"
    assert root["root_cause_id"] == "rc-verify"
    assert validate_failure_ir(failure) == []
    assert validate_preservation_ir(preservation) == []
    assert validate_root_cause_ir(root) == []


def test_failure_ir_rejects_representation_and_hidden_execution_fields():
    for key in ("artifact_type", "kind", "representation", "expert_plan", "pddl_plan", "hidden_state"):
        value = _failure()
        value[key] = "forbidden"
        assert validate_failure_ir(value)
        try:
            normalize_failure_ir(value)
        except IRValidationError:
            pass
        else:
            raise AssertionError("invalid IR unexpectedly normalized")


def test_failure_ir_requires_trace_step_refs_and_defect_enum():
    missing_steps = _failure()
    del missing_steps["evidence"]["trajectory_steps"]
    del missing_steps["location"]["trajectory_steps"]
    assert validate_failure_ir(missing_steps)
    bad_defect = _failure(defect_type="made_up_defect")
    assert validate_failure_ir(bad_defect)


def test_preservation_and_root_cause_require_supported_refs_and_valid_scope():
    bad_preservation = _preservation(supported_by=[])
    assert validate_preservation_ir(bad_preservation)
    bad_root = _root(scope={"level": "instance", "target": "trial_1"})
    assert validate_root_cause_ir(bad_root)
    bad_root = _root(supported_by=[{"failure_id": "failure-1"}])
    assert validate_root_cause_ir(bad_root)
