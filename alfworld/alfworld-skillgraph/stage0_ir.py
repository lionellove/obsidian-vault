"""Strict, representation-neutral IR contracts for Stage 0 evolution.

The objects in this module are deliberately ordinary dictionaries.  Keeping
the public seam dependency-free makes it possible to run the analyzer and
merger tests without an ALFWorld install or a model endpoint.  Validation is
fail-closed: an IR object containing execution artifacts, hidden expert/PDDL
state, or an instance-scoped claim is never normalized into the pipeline.
"""

from __future__ import annotations

import copy
import math
from typing import Any, Iterable

from stage0_core import FAMILIES, SCOPE_LEVELS


class IRValidationError(ValueError):
    """Raised when an IR value cannot be safely normalized."""


DEFECT_TYPES = {
    "missing_prerequisite",
    "wrong_ordering",
    "missing_state_confirmation",
    "recovery_failure",
    "repeated_exploration",
    "constraint_violation",
    "non_skill_execution_error",
    "insufficient_evidence",
    "unknown",
}
PATCHABILITY = {"skill_patchable", "non_skill_execution_error", "unknown"}
_FORBIDDEN_EXACT = {
    "artifact",
    "artifact_kind",
    "artifact_type",
    "kind",
    "hidden_state",
    "hidden_state_trace",
    "expert_plan",
    "expert_trajectory",
    "pddl_plan",
    "pddl_state",
    "representation",
    "representation_kind",
    "instance_scope",
    "target_location",
}
_FORBIDDEN_SUBSTRINGS = ("expert", "pddl", "hidden_state")
_ALLOWED_SCOPE_LEVELS = SCOPE_LEVELS - {"instance"}


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _finite_confidence(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and 0 <= float(value) <= 1
    )


def _walk_forbidden(value: Any, path: str, errors: list[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                errors.append(f"non-string IR key at {path}")
                continue
            lowered = key.casefold()
            if lowered in _FORBIDDEN_EXACT or any(part in lowered for part in _FORBIDDEN_SUBSTRINGS):
                errors.append(f"forbidden hidden/representation field: {path}.{key}")
            if lowered.startswith("_"):
                errors.append(f"private IR field is forbidden: {path}.{key}")
            _walk_forbidden(child, f"{path}.{key}", errors)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_forbidden(child, f"{path}[{index}]", errors)


def _scope_errors(scope: Any, owner: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(scope, dict) or not scope:
        return [f"missing or empty scope: {owner}"]
    level = scope.get("level")
    if level == "instance":
        return [f"instance scope forbidden: {owner}"]
    if level not in _ALLOWED_SCOPE_LEVELS:
        errors.append(f"invalid scope level: {owner}")
        return errors
    target = scope.get("target")
    if level == "task_family" and target not in FAMILIES:
        errors.append(f"invalid task_family scope target: {owner}")
    elif level in {"global", "workflow"} and "target" in scope and not _nonempty(target):
        errors.append(f"scope target must be a non-empty string: {owner}")
    elif level == "local" and not _nonempty(target):
        # Local node existence is checked by the Skill validator.  IR has no
        # package map, but it still rejects an empty/non-addressable target.
        errors.append(f"local scope target must be non-empty: {owner}")
    return errors


def _steps(value: Any, owner: str) -> list[str]:
    if not isinstance(value, list) or not value:
        return [f"{owner} must contain non-empty trajectory_steps"]
    errors: list[str] = []
    for step in value:
        if isinstance(step, bool) or not isinstance(step, int) or step < 0:
            errors.append(f"{owner} trajectory_steps must be non-negative integers")
    return errors


def _ref_errors(value: Any, owner: str, *, require_failure: bool = False) -> list[str]:
    """Validate a trace/evidence reference without exposing raw trajectory."""

    if isinstance(value, str):
        return [] if _nonempty(value) else [f"empty reference: {owner}"]
    if not isinstance(value, dict):
        return [f"invalid reference: {owner}"]
    errors: list[str] = []
    if not _nonempty(value.get("trace_id")):
        errors.append(f"reference missing trace_id: {owner}")
    if require_failure and not _nonempty(value.get("failure_id")):
        errors.append(f"reference missing failure_id: {owner}")
    if "task_id" in value and not _nonempty(value.get("task_id")):
        errors.append(f"reference task_id must be non-empty: {owner}")
    if "trajectory_steps" in value:
        errors.extend(_steps(value["trajectory_steps"], owner))
    return errors


def _unwrap(value: Any, key: str) -> Any:
    if isinstance(value, dict) and key in value:
        if len(value) != 1:
            # Keep semantic fields visible; callers get a useful field error
            # rather than silently discarding siblings.
            return value
        return value[key]
    return value


def validate_failure_ir(value: Any) -> list[str]:
    errors: list[str] = []
    value = _unwrap(value, "failure")
    _walk_forbidden(value, "failure", errors)
    if not isinstance(value, dict):
        return errors + ["failure IR must be an object"]
    if not _nonempty(value.get("failure_id")):
        errors.append("failure_id must be non-empty")
    if "trace_id" in value and not _nonempty(value.get("trace_id")):
        errors.append("trace_id must be non-empty")
    if "task_id" in value and not _nonempty(value.get("task_id")):
        errors.append("task_id must be non-empty")
    if value.get("defect_type") not in DEFECT_TYPES:
        errors.append("invalid defect_type")
    errors.extend(_scope_errors(value.get("scope"), "failure"))
    location = value.get("location")
    if not isinstance(location, dict):
        errors.append("location must be an object")
    else:
        errors.extend(_steps(location.get("trajectory_steps"), "location"))
        related = location.get("related_skill_ids", [])
        if not isinstance(related, list) or any(not _nonempty(item) for item in related):
            errors.append("location related_skill_ids must be a list of non-empty strings")
    evidence = value.get("evidence")
    if not isinstance(evidence, dict):
        errors.append("evidence must be an object")
    else:
        if not _nonempty(evidence.get("observation")):
            errors.append("evidence observation must be non-empty")
        if not _nonempty(evidence.get("expected_semantics")):
            errors.append("evidence expected_semantics must be non-empty")
        if "trace_id" in evidence and not _nonempty(evidence.get("trace_id")):
            errors.append("evidence trace_id must be non-empty")
        if "trajectory_steps" in evidence:
            errors.extend(_steps(evidence["trajectory_steps"], "evidence"))
    if not _nonempty(value.get("cause")):
        errors.append("cause must be non-empty")
    if value.get("patchability") not in PATCHABILITY:
        errors.append("invalid patchability")
    if not _finite_confidence(value.get("confidence")):
        errors.append("confidence must be a number between 0 and 1")
    return errors


def validate_preservation_ir(value: Any) -> list[str]:
    errors: list[str] = []
    value = _unwrap(value, "preservation")
    _walk_forbidden(value, "preservation", errors)
    if not isinstance(value, dict):
        return errors + ["preservation IR must be an object"]
    if not _nonempty(value.get("preservation_id")):
        errors.append("preservation_id must be non-empty")
    if not _nonempty(value.get("behavior")):
        errors.append("behavior must be non-empty")
    errors.extend(_scope_errors(value.get("scope"), "preservation"))
    supported = value.get("supported_by")
    if not isinstance(supported, list) or not supported:
        errors.append("supported_by must be non-empty")
    else:
        for index, ref in enumerate(supported):
            errors.extend(_ref_errors(ref, f"supported_by[{index}]"))
    related = value.get("related_skill_ids", [])
    if not isinstance(related, list) or any(not _nonempty(item) for item in related):
        errors.append("related_skill_ids must be a list of non-empty strings")
    if "trace_id" in value and not _nonempty(value.get("trace_id")):
        errors.append("trace_id must be non-empty")
    if "task_id" in value and not _nonempty(value.get("task_id")):
        errors.append("task_id must be non-empty")
    if not _finite_confidence(value.get("confidence")):
        errors.append("confidence must be a number between 0 and 1")
    return errors


def validate_root_cause_ir(value: Any) -> list[str]:
    errors: list[str] = []
    value = _unwrap(value, "root_cause")
    _walk_forbidden(value, "root_cause", errors)
    if not isinstance(value, dict):
        return errors + ["root cause IR must be an object"]
    if not _nonempty(value.get("root_cause_id")):
        errors.append("root_cause_id must be non-empty")
    if not _nonempty(value.get("semantic_defect")):
        errors.append("semantic_defect must be non-empty")
    errors.extend(_scope_errors(value.get("scope"), "root_cause"))
    supported = value.get("supported_by")
    if not isinstance(supported, list) or not supported:
        errors.append("supported_by must be non-empty")
    else:
        for index, ref in enumerate(supported):
            errors.extend(_ref_errors(ref, f"supported_by[{index}]", require_failure=True))
    contradictions = value.get("contradictory_evidence")
    if not isinstance(contradictions, list):
        errors.append("contradictory_evidence must be a list")
    else:
        for index, item in enumerate(contradictions):
            if not _nonempty(item) and not isinstance(item, dict):
                errors.append(f"contradictory_evidence[{index}] must be text or an object")
            elif isinstance(item, dict):
                errors.extend(_ref_errors(item, f"contradictory_evidence[{index}]"))
    if value.get("patchability") not in PATCHABILITY:
        errors.append("invalid patchability")
    priority = value.get("priority")
    if isinstance(priority, bool) or not isinstance(priority, int) or priority < 1:
        errors.append("priority must be a positive integer")
    if "confidence" in value and not _finite_confidence(value.get("confidence")):
        errors.append("confidence must be a number between 0 and 1")
    return errors


def _normalize(value: Any, validator, label: str) -> dict:
    candidate = copy.deepcopy(value)
    errors = validator(candidate)
    if errors:
        raise IRValidationError(f"invalid {label}: " + "; ".join(errors))
    return candidate.get(label) if isinstance(candidate, dict) and set(candidate) == {label} else candidate


def normalize_failure_ir(value: Any) -> dict:
    return _normalize(value, validate_failure_ir, "failure")


def normalize_preservation_ir(value: Any) -> dict:
    return _normalize(value, validate_preservation_ir, "preservation")


def normalize_root_cause_ir(value: Any) -> dict:
    return _normalize(value, validate_root_cause_ir, "root_cause")


def normalize_root_cause_candidates(value: Any) -> list[dict]:
    """Normalize a merger envelope containing one or more Root Causes."""

    if isinstance(value, dict) and "root_causes" in value:
        value = value["root_causes"]
    elif isinstance(value, dict) and "root_cause" in value:
        value = [value["root_cause"]]
    elif isinstance(value, dict) and value.get("status") == "NO_ROOT_CAUSE":
        value = []
    elif isinstance(value, dict) and "root_cause_id" in value:
        value = [value]
    if not isinstance(value, list):
        raise IRValidationError("root_causes must be a list")
    return [normalize_root_cause_ir(item) for item in value]


def normalize_failure_batch(values: Iterable[Any]) -> list[dict]:
    return [normalize_failure_ir(value) for value in values]


def normalize_preservation_batch(values: Iterable[Any]) -> list[dict]:
    return [normalize_preservation_ir(value) for value in values]


__all__ = [
    "DEFECT_TYPES",
    "IRValidationError",
    "PATCHABILITY",
    "normalize_failure_batch",
    "normalize_failure_ir",
    "normalize_preservation_batch",
    "normalize_preservation_ir",
    "normalize_root_cause_candidates",
    "normalize_root_cause_ir",
    "validate_failure_ir",
    "validate_preservation_ir",
    "validate_root_cause_ir",
]
