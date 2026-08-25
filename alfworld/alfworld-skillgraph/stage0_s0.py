"""Common initial Skill Package (S0) generation and human-gate seam."""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from stage0_core import FAMILIES, SCHEMA_VERSION, SCOPE_LEVELS, NODE_TYPES, canonical, render_skill, sha256, validate_skill
from stage0_format import normalize_json_response


S0_GATE_FIELDS = (
    "schema_valid",
    "no_instance_leakage",
    "six_family_applicable",
    "no_contradiction",
    "within_budget",
)


PUBLIC_S0_CONTEXT: dict[str, Any] = {
    "public_task_families": [
        {"name": "pick_and_place", "definition": "acquire an object and place it in a target receptacle"},
        {"name": "examine_in_light", "definition": "inspect an object under the required lighting condition"},
        {"name": "clean_and_place", "definition": "clean an object and place it in a target receptacle"},
        {"name": "heat_and_place", "definition": "heat an object and place it in a target receptacle"},
        {"name": "cool_and_place", "definition": "cool an object and place it in a target receptacle"},
        {"name": "pick_two_and_place", "definition": "acquire two objects and place them as required"},
    ],
    "action_observation_semantics": {
        "action": "choose exactly one currently admissible environment action",
        "observation": "natural-language observation returned after an action",
        "success": "the task goal is satisfied",
        "failure": "the episode terminates without satisfying the task goal",
    },
    "skill_package_schema": {
        "schema_version": SCHEMA_VERSION,
        "node_types": sorted(NODE_TYPES),
        "scope_levels": sorted(SCOPE_LEVELS - {"instance"}),
        "required_sections": ["nodes", "edges", "constraints", "verifications", "fallbacks"],
        "budget": {"workflow_nodes": "6-12", "non_workflow_each": "0-8", "rendered_words": 1200},
    },
    "renderer_format": {
        "order": ["workflow_nodes", "edges", "constraints", "verifications", "fallbacks"],
        "text": "deterministic UTF-8 renderer with one line per package element",
    },
}


def _content(value: Any) -> Any:
    return getattr(value, "content", value)


def _record(value: Any) -> dict | None:
    record = getattr(value, "record", None)
    return copy.deepcopy(record) if isinstance(record, dict) else None


def _has_forbidden_instance_text(skill: dict) -> bool:
    text = canonical(skill).casefold()
    return any(token in text for token in ("game.tw-pddl", "trial_", "valid_seen", "valid_unseen", "expert_plan", "pddl_plan", "target_location", "object_id", "receptacle_id")) or bool(re.search(r"\bscene[_ -]?\d+\b", text))


def _has_contradiction(skill: dict) -> bool:
    statements: list[str] = []
    package = skill.get("skill_package", {}) if isinstance(skill, dict) else {}
    for key in ("nodes", "constraints", "verifications", "fallbacks"):
        for item in package.get(key, []) if isinstance(package, dict) else []:
            if isinstance(item, dict):
                for field_name in ("instruction", "rule", "criterion", "trigger"):
                    if isinstance(item.get(field_name), str):
                        statements.append(item[field_name].casefold())
    for statement in statements:
        if "always" in statement and "never" in statement:
            return True
    return False


def s0_gate_checklist(skill: Any) -> tuple[dict[str, bool], list[str]]:
    structural_errors = validate_skill(skill, enforce_budget=True) if isinstance(skill, dict) else ["skill must be an object"]
    checklist = {
        "schema_valid": not structural_errors,
        "no_instance_leakage": isinstance(skill, dict) and not _has_forbidden_instance_text(skill),
        "six_family_applicable": isinstance(skill, dict) and not any(
            family not in FAMILIES and family in canonical(skill).casefold() for family in FAMILIES
        ),
        "no_contradiction": isinstance(skill, dict) and not _has_contradiction(skill),
        "within_budget": not structural_errors,
    }
    feedback = [field_name for field_name in S0_GATE_FIELDS if not checklist[field_name]]
    return checklist, feedback


@dataclass
class S0GenerationResult:
    status: str
    skill: dict | None
    gate_checklist: dict[str, bool]
    gate_feedback: list[str]
    generation_prompt: str
    raw_response: Any
    request_records: list[dict] = field(default_factory=list)
    rendered_skill: str | None = None
    skill_hash: str | None = None
    attempts: int = 0
    approval: dict | None = None

    def approve(self, checklist: dict[str, bool], auditor: str, timestamp: str | None = None) -> dict:
        if set(checklist) != set(S0_GATE_FIELDS) or any(not isinstance(checklist[key], bool) for key in S0_GATE_FIELDS):
            raise ValueError("human gate checklist must contain exactly five boolean fields")
        if checklist != self.gate_checklist or not all(checklist.values()):
            raise ValueError("human gate cannot override failed S0 gate entries")
        if not isinstance(auditor, str) or not auditor.strip():
            raise ValueError("auditor is required")
        stamp = timestamp or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self.approval = {"checklist": copy.deepcopy(checklist), "auditor": auditor, "timestamp": stamp}
        return copy.deepcopy(self.approval)


class S0Generator:
    """Generate S0 without access to any task instance or trajectory."""

    def __init__(self, client: Any, *, token_budget: int = 2048, max_attempts: int = 3) -> None:
        if isinstance(token_budget, bool) or not isinstance(token_budget, int) or token_budget <= 0:
            raise ValueError("token_budget must be a positive integer")
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or not 1 <= max_attempts <= 3:
            raise ValueError("max_attempts must be between 1 and 3")
        self.client = client
        self.token_budget = token_budget
        self.max_attempts = max_attempts

    def _request(self, context: dict) -> Any:
        method = getattr(self.client, "complete_meta", None)
        if method is None:
            raise TypeError("S0 client must provide complete_meta")
        return method(role="s0_generator", context=context, token_budget=self.token_budget)

    def generate(self) -> S0GenerationResult:
        context = copy.deepcopy(PUBLIC_S0_CONTEXT)
        prompt = canonical(context)
        records: list[dict] = []
        raw_response: Any = None
        checklist = {field_name: False for field_name in S0_GATE_FIELDS}
        feedback: list[str] = []
        skill: dict | None = None
        for attempt in range(1, self.max_attempts + 1):
            if feedback:
                context = copy.deepcopy(PUBLIC_S0_CONTEXT)
                context["gate_feedback"] = list(feedback)
            raw = self._request(context)
            raw_response = _content(raw)
            record = _record(raw)
            if record:
                records.append(record)
            try:
                candidate = normalize_json_response(raw_response)
            except (TypeError, ValueError) as exc:
                skill = None
                checklist = {field_name: False for field_name in S0_GATE_FIELDS}
                feedback = ["schema_valid"]
                continue
            candidate_checklist, candidate_feedback = s0_gate_checklist(candidate)
            checklist = candidate_checklist
            feedback = candidate_feedback
            if all(checklist.values()):
                skill = candidate
                break
        if skill is None:
            return S0GenerationResult(
                status="s0_generation_failed",
                skill=None,
                gate_checklist=checklist,
                gate_feedback=feedback,
                generation_prompt=prompt,
                raw_response=raw_response,
                request_records=records,
                attempts=self.max_attempts,
            )
        rendered = render_skill(skill)
        return S0GenerationResult(
            status="awaiting_human_gate",
            skill=skill,
            gate_checklist=checklist,
            gate_feedback=[],
            generation_prompt=prompt,
            raw_response=raw_response,
            request_records=records,
            rendered_skill=rendered,
            skill_hash=sha256(canonical(skill)),
            attempts=attempt,
        )


__all__ = [
    "PUBLIC_S0_CONTEXT",
    "S0_GATE_FIELDS",
    "S0GenerationResult",
    "S0Generator",
    "s0_gate_checklist",
]
