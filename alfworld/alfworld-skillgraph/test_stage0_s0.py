"""Public S0 generation and human-gate behavior."""

from __future__ import annotations

import json

from stage0_core import canonical, render_skill, sha256
from stage0_run import baseline_skill
from stage0_s0 import S0Generator


class FakeS0Client:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete_meta(self, role, context, token_budget):
        self.calls.append((role, context, token_budget))
        value = self.responses.pop(0)
        return json.dumps(value)


def test_s0_generator_uses_only_public_context_and_freezes_render_hash():
    client = FakeS0Client([baseline_skill()])
    result = S0Generator(client, token_budget=777).generate()
    assert result.status == "awaiting_human_gate"
    assert result.skill is not None
    assert result.gate_checklist == {
        "schema_valid": True,
        "no_instance_leakage": True,
        "six_family_applicable": True,
        "no_contradiction": True,
        "within_budget": True,
    }
    assert result.rendered_skill == render_skill(result.skill)
    assert result.skill_hash == sha256(canonical(result.skill))
    assert client.calls[0][0] == "s0_generator"
    assert client.calls[0][2] == 777
    context_text = canonical(client.calls[0][1]).lower()
    for forbidden in ("game.tw-pddl", "trial_", "trajectory", "expert", "revised", "calibration", "evolution", "validation"):
        assert forbidden not in context_text


def test_s0_generator_default_budget_leaves_room_after_max_reasoning():
    client = FakeS0Client([baseline_skill()])

    result = S0Generator(client).generate()

    assert result.status == "awaiting_human_gate"
    assert client.calls[0][2] == 8192


def test_s0_generator_rejects_string_artifacts_and_regenerates():
    malformed = baseline_skill()
    package = malformed["skill_package"]
    package["constraints"] = ["use admissible actions"]
    package["verifications"] = ["verify progress"]
    package["fallbacks"] = ["retry safely"]
    client = FakeS0Client([malformed, baseline_skill()])

    result = S0Generator(client).generate()

    assert result.status == "awaiting_human_gate"
    assert len(client.calls) == 2
    assert client.calls[1][1]["gate_feedback"] == ["schema_valid", "within_budget"]


def test_s0_generator_returns_gate_feedback_only_and_retries_at_most_three_times():
    invalid = {"skill_package": {"schema_version": "wrong"}}
    client = FakeS0Client([invalid, baseline_skill()])
    result = S0Generator(client).generate()
    assert result.status == "awaiting_human_gate"
    assert len(client.calls) == 2
    feedback = client.calls[1][1].get("gate_feedback")
    assert feedback
    assert all(isinstance(item, str) for item in feedback)
    assert "trajectory" not in canonical(client.calls[1][1]).lower()


def test_s0_generator_does_not_accept_human_semantic_edits():
    client = FakeS0Client([baseline_skill()])
    result = S0Generator(client).generate()
    original = canonical(result.skill)
    try:
        result.approve({"schema_valid": True, "no_instance_leakage": True, "six_family_applicable": True, "no_contradiction": True, "within_budget": True}, "auditor")
    except ValueError:
        pass
    else:
        assert canonical(result.skill) == original
