"""Public candidate and blind semantic verification behavior."""

from __future__ import annotations

from stage0_core import canonical
from stage0_verifier import (
    CandidateResult,
    blind_semantic_verify,
    verify_structured_candidate,
    verify_rewrite_candidate,
)


def _skill():
    nodes = []
    for index in range(6):
        nodes.append(
            {
                "id": f"node-{index}",
                "type": "action" if index < 5 else "terminal",
                "instruction": f"Perform step {index}.",
                "scope": {"level": "task_family", "target": "pick_and_place"},
            }
        )
    return {
        "skill_package": {
            "schema_version": "0.1",
            "package_id": "baseline",
            "entry_node": "node-0",
            "nodes": nodes,
            "edges": [
                {
                    "id": f"edge-{index}",
                    "source": f"node-{index}",
                    "target": f"node-{index + 1}",
                    "condition": "continue",
                }
                for index in range(5)
            ],
            "constraints": [],
            "verifications": [],
            "fallbacks": [],
        }
    }


def _patch():
    return {
        "semantic_patch": {
            "diagnosis_binding": {"root_cause_id": "rc-verify"},
            "edits": [
                {
                    "op": "ADD",
                    "kind": "CONSTRAINT",
                    "target_id": "constraint-verify",
                    "value": {
                        "id": "constraint-verify",
                        "rule": "Verify the destination before completion.",
                        "scope": {"level": "task_family", "target": "pick_and_place"},
                    },
                    "addresses": ["rc-verify"],
                }
            ],
        }
    }


def _rewrite(skill):
    package = dict(skill["skill_package"])
    package["constraints"] = [
        {
            "id": "constraint-verify",
            "rule": "Verify the destination before completion.",
            "scope": {"level": "task_family", "target": "pick_and_place"},
        }
    ]
    return {
        "full_rewrite": {
            "diagnosis_binding": {"root_cause_id": "rc-verify"},
            "rewritten_skill_package": package,
            "change_manifest": [
                {
                    "change": "ADD",
                    "kind": "CONSTRAINT",
                    "target_id": "constraint-verify",
                    "addresses": ["rc-verify"],
                }
            ],
        }
    }


def test_structured_and_rewrite_candidates_are_structurally_checked():
    skill = _skill()
    structured = verify_structured_candidate(skill, _patch(), "rc-verify")
    rewritten = verify_rewrite_candidate(skill, _rewrite(skill), "rc-verify")
    assert isinstance(structured, CandidateResult)
    assert structured.status == "VALID"
    assert structured.eligible_for_dynamic_validation is True
    assert rewritten.status == "VALID"
    assert rewritten.structural_result["diff"]


def test_no_patch_is_not_dynamically_validated():
    result = verify_structured_candidate(
        _skill(), {"status": "NO_PATCH", "reason": "not patchable"}, "rc-verify"
    )
    assert result.status == "NO_PATCH"
    assert result.eligible_for_dynamic_validation is False
    assert result.structural_result is None


def test_blind_semantic_verifier_hides_method_scores_and_generator_labels():
    seen = []

    class FakeVerifier:
        def complete_meta(self, role, context, token_budget):
            seen.append((role, context, token_budget))
            return '{"relevance":0.1,"generality":0.2,"contradiction":0.3,"redundancy":0.4,"over_specificity":0.5,"root_cause_coverage":0.6,"preservation_risk":0.7}'

    result = blind_semantic_verify(
        {"root_cause_id": "rc-verify", "semantic_defect": "missing verification"},
        {"preservation_id": "p-1", "behavior": "keep verification"},
        {"edits": [{"op": "ADD", "kind": "CONSTRAINT"}]},
        FakeVerifier(),
        token_budget=99,
    )
    assert result.eligible_for_dynamic_validation is True
    assert result.scores["relevance"] == 0.1
    assert seen[0][0] == "semantic_verifier"
    context_text = canonical(seen[0][1])
    assert "structured_patch" not in context_text
    assert "full_rewrite" not in context_text
    assert "generator" not in context_text
    assert "score" not in context_text

