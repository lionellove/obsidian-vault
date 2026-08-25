from contextlib import contextmanager

try:
    import pytest  # type: ignore
except ImportError:  # Keep the suite runnable with only the standard library.
    pytest = None

from stage0_core import (
    apply_patch,
    diff_skill,
    paired_outcomes,
    render_skill,
    sha256,
    validate_full_rewrite,
    validate_skill,
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


def skill():
    return {"skill_package": {
        "schema_version": "0.1", "package_id": "test", "entry_node": "start",
        "nodes": [{"id": "start", "type": "decision", "instruction": "parse", "scope": {"level": "global"}},
                   {"id": "done", "type": "terminal", "instruction": "finish", "scope": {"level": "global"}}],
        "edges": [{"id": "e1", "source": "start", "target": "done", "condition": "ready"}],
        "constraints": [], "verifications": [], "fallbacks": []}}


def test_valid_and_deterministic_renderer():
    s = skill()
    assert validate_skill(s) == []
    expected = (
        'SKILL PACKAGE test schema=0.1\n'
        'ENTRY: start\n'
        'WORKFLOW:\n'
        '- NODE start [decision] scope={"level":"global"}: parse\n'
        '- NODE done [terminal] scope={"level":"global"}: finish\n'
        '- EDGE e1: start -> done when ready\n'
        'CONSTRAINTS:\n'
        'VERIFICATIONS:\n'
        'FALLBACKS:\n'
    )
    assert render_skill(s) == expected
    assert sha256(expected) == '70b447b933c1f717c3365eb298587574b0a0d78a323d93851958d6156f4a23f7'


def test_patch_apply_and_diff():
    s = skill()
    patch = {"semantic_patch": {"diagnosis_binding": {"root_cause_id": "rc1"}, "edits": [{
        "op": "ADD", "kind": "CONSTRAINT", "addresses": ["rc1"],
        "value": {"id": "c1", "rule": "use admissible actions", "scope": {"level": "global"}}}]}}
    out = apply_patch(s, patch, "rc1")
    assert validate_skill(out) == []
    assert diff_skill(s, out) == [{"change": "ADD", "kind": "CONSTRAINT", "target_id": "c1"}]


def test_invalid_dangling_reference_rejected():
    s = skill()
    s["skill_package"]["edges"][0]["target"] = "missing"
    assert any("dangling" in e for e in validate_skill(s))


def test_paired_outcomes():
    b = [{"task_id": "a", "success": False}, {"task_id": "b", "success": True}]
    c = [{"task_id": "a", "success": True}, {"task_id": "b", "success": False}]
    rows = paired_outcomes(b, c)
    assert rows[-1]["summary"] == {
        "repairs": 1,
        "regressions": 1,
        "stable_success": 0,
        "stable_failure": 0,
        "NetGain": 0,
        "net_gain": 0,
        "n": 2,
    }


def test_paired_outcomes_rejects_duplicates_and_set_mismatch():
    with raises(ValueError):
        paired_outcomes([{"task_id": "a", "success": True}, {"task_id": "a", "success": False}], [{"task_id": "a", "success": True}])
    with raises(ValueError):
        paired_outcomes([{"task_id": "a", "success": True}], [{"task_id": "b", "success": True}])


def test_full_rewrite_manifest_matches_real_diff():
    s = skill()
    after = {"skill_package": {**s["skill_package"], "package_id": "changed"}}
    rewrite = {
        "full_rewrite": {
            "diagnosis_binding": {"root_cause_id": "rc1"},
            "rewritten_skill_package": after["skill_package"],
            "change_manifest": [{
                "change": "UPDATE", "kind": "PACKAGE", "target_id": "package_id",
                "addresses": ["rc1"], "rationale": "same diagnosis",
            }],
        }
    }
    assert validate_full_rewrite(s, rewrite, "rc1") == []
    rewrite["full_rewrite"]["change_manifest"][0]["target_id"] = "entry_node"
    assert any("canonical IR diff" in error for error in validate_full_rewrite(s, rewrite, "rc1"))


def test_patch_requires_explicit_addresses_and_target_shapes():
    s = skill()
    missing_addresses = {"semantic_patch": {"diagnosis_binding": {"root_cause_id": "rc1"}, "edits": [{
        "op": "ADD", "kind": "CONSTRAINT", "value": {"id": "c1", "rule": "r", "scope": {"level": "global"}},
    }]}}
    with raises(ValueError):
        apply_patch(s, missing_addresses, "rc1")
    empty_addresses = {"semantic_patch": {"diagnosis_binding": {"root_cause_id": "rc1"}, "edits": [{
        "op": "ADD", "kind": "CONSTRAINT", "addresses": [], "value": {"id": "c1", "rule": "r", "scope": {"level": "global"}},
    }]}}
    with raises(ValueError):
        apply_patch(s, empty_addresses, "rc1")
    duplicate_addresses = {"semantic_patch": {"diagnosis_binding": {"root_cause_id": "rc1"}, "edits": [{
        "op": "ADD", "kind": "CONSTRAINT", "addresses": ["rc1", "rc1"],
        "value": {"id": "c1", "rule": "r", "scope": {"level": "global"}},
    }]}}
    with raises(ValueError):
        apply_patch(s, duplicate_addresses, "rc1")


def test_all_scoped_artifacts_reject_invalid_scope_targets():
    constraint_bad_level = skill()
    constraint_bad_level["skill_package"]["constraints"] = [{
        "id": "c1", "rule": "r", "scope": {"level": "bogus"},
    }]
    assert any("scope level" in error for error in validate_skill(constraint_bad_level))

    constraint_bad_family = skill()
    constraint_bad_family["skill_package"]["constraints"] = [{
        "id": "c1", "rule": "r", "scope": {"level": "task_family", "target": "not_a_family"},
    }]
    assert any("task_family" in error for error in validate_skill(constraint_bad_family))

    local_node = skill()
    local_node["skill_package"]["nodes"][0]["scope"] = {"level": "local", "target": "missing_node"}
    assert any("local scope target" in error for error in validate_skill(local_node))

    verification_bad = skill()
    verification_bad["skill_package"]["verifications"] = [{
        "id": "v1", "target": "done", "on_failure": "f1", "criterion": "c",
        "scope": {"level": "bogus"},
    }]
    verification_bad["skill_package"]["fallbacks"] = [{
        "id": "f1", "target": "done", "trigger": "retry", "max_retries": 1,
        "scope": {"level": "global"},
    }]
    assert any("scope level" in error for error in validate_skill(verification_bad))

    fallback_bad = skill()
    fallback_bad["skill_package"]["fallbacks"] = [{
        "id": "f1", "target": "done", "trigger": "retry", "max_retries": 1,
        "scope": {"level": "local", "target": "missing_node"},
    }]
    assert any("local scope target" in error for error in validate_skill(fallback_bad))
