"""Structural candidate checks and the blind, non-veto semantic audit seam."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any

from stage0_core import apply_patch, diff_skill, validate_full_rewrite
from stage0_format import FormatRepairResult, format_json_with_repairs, normalize_json_response


SEMANTIC_FIELDS = (
    "relevance",
    "generality",
    "contradiction",
    "redundancy",
    "over_specificity",
    "root_cause_coverage",
    "preservation_risk",
)


def _raw_content(value: Any) -> Any:
    return getattr(value, "content", value)


def _request_record(value: Any) -> dict | None:
    record = getattr(value, "record", None)
    return copy.deepcopy(record) if isinstance(record, dict) else None


@dataclass
class CandidateResult:
    method: str
    status: str
    raw_response: Any
    final_ir: dict | None = None
    format_repairs: list[dict] = field(default_factory=list)
    structural_result: dict | None = None
    eligible_for_dynamic_validation: bool = False
    request_records: list[dict] = field(default_factory=list)
    error: str | None = None

    @property
    def candidate_ir(self) -> dict | None:
        return self.final_ir

    @property
    def valid(self) -> bool:
        return self.status == "VALID"

    @property
    def structural_valid(self) -> bool:
        return bool(self.structural_result and self.structural_result.get("valid") is True)

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "status": self.status,
            "raw_response": self.raw_response,
            "final_ir": copy.deepcopy(self.final_ir),
            "format_repairs": copy.deepcopy(self.format_repairs),
            "structural_result": copy.deepcopy(self.structural_result),
            "eligible_for_dynamic_validation": self.eligible_for_dynamic_validation,
            "request_records": copy.deepcopy(self.request_records),
            "error": self.error,
        }


@dataclass
class VerifierResult:
    scores: dict[str, float] = field(default_factory=dict)
    eligible_for_dynamic_validation: bool = True
    raw_response: Any = None
    request_record: dict | None = None
    valid: bool = True
    error: str | None = None

    def __getattr__(self, name: str) -> Any:
        if name in SEMANTIC_FIELDS:
            return self.scores.get(name)
        raise AttributeError(name)

    def to_dict(self) -> dict:
        return {
            "scores": copy.deepcopy(self.scores),
            "eligible_for_dynamic_validation": self.eligible_for_dynamic_validation,
            "raw_response": self.raw_response,
            "request_record": copy.deepcopy(self.request_record),
            "valid": self.valid,
            "error": self.error,
        }


def _format_candidate(raw: Any, repairer: Any, expected_fingerprint: str | None) -> FormatRepairResult:
    return format_json_with_repairs(
        _raw_content(raw),
        repairer,
        expected_fingerprint=expected_fingerprint,
        max_repairs=3,
    )


def _no_patch(value: Any) -> bool:
    return isinstance(value, dict) and str(value.get("status", "")).upper() == "NO_PATCH"


def _invalid(method: str, raw: Any, *, repairs: list[dict] | None = None, error: str) -> CandidateResult:
    return CandidateResult(
        method=method,
        status="INVALID",
        raw_response=_raw_content(raw),
        format_repairs=repairs or [],
        structural_result={"valid": False, "errors": [error]},
        eligible_for_dynamic_validation=False,
        request_records=[_request_record(raw)] if _request_record(raw) else [],
        error=error,
    )


def _finish_no_patch(method: str, raw: Any, value: dict, repairs: list[dict]) -> CandidateResult:
    reason = value.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        return _invalid(method, raw, repairs=repairs, error="NO_PATCH requires a non-empty reason")
    return CandidateResult(
        method=method,
        status="NO_PATCH",
        raw_response=_raw_content(raw),
        final_ir=value,
        format_repairs=repairs,
        structural_result=None,
        eligible_for_dynamic_validation=False,
        request_records=[_request_record(raw)] if _request_record(raw) else [],
    )


def verify_structured_candidate(
    current_skill: dict,
    raw_response: Any,
    root_cause_id: str,
    repairer: Any = None,
    *,
    expected_fingerprint: str | None = None,
    enforce_budget: bool = True,
) -> CandidateResult:
    """Parse and structurally apply one Structured Semantic Patch candidate."""

    formatted = _format_candidate(raw_response, repairer, expected_fingerprint)
    if not formatted.valid or formatted.value is None:
        return _invalid(
            "structured_patch",
            raw_response,
            repairs=formatted.records,
            error=formatted.error or "invalid structured patch JSON",
        )
    value = formatted.value
    if _no_patch(value):
        return _finish_no_patch("structured_patch", raw_response, value, formatted.records)
    try:
        patched = apply_patch(current_skill, value, root_cause_id, enforce_budget=enforce_budget)
    except (TypeError, ValueError, KeyError) as exc:
        return _invalid("structured_patch", raw_response, repairs=formatted.records, error=str(exc))
    return CandidateResult(
        method="structured_patch",
        status="VALID",
        raw_response=_raw_content(raw_response),
        final_ir=value,
        format_repairs=formatted.records,
        structural_result={"valid": True, "errors": [], "skill": patched, "diff": diff_skill(current_skill, patched)},
        eligible_for_dynamic_validation=True,
        request_records=[_request_record(raw_response)] if _request_record(raw_response) else [],
    )


def verify_rewrite_candidate(
    current_skill: dict,
    raw_response: Any,
    root_cause_id: str,
    repairer: Any = None,
    *,
    expected_fingerprint: str | None = None,
    enforce_budget: bool = True,
) -> CandidateResult:
    """Parse a Full Rewrite and require its manifest to equal the real diff."""

    formatted = _format_candidate(raw_response, repairer, expected_fingerprint)
    if not formatted.valid or formatted.value is None:
        return _invalid(
            "full_rewrite",
            raw_response,
            repairs=formatted.records,
            error=formatted.error or "invalid full rewrite JSON",
        )
    value = formatted.value
    if _no_patch(value):
        return _finish_no_patch("full_rewrite", raw_response, value, formatted.records)
    errors = validate_full_rewrite(current_skill, value, root_cause_id, enforce_budget=enforce_budget)
    if errors:
        return _invalid("full_rewrite", raw_response, repairs=formatted.records, error="; ".join(errors))
    rewritten = {"skill_package": value.get("full_rewrite", value)["rewritten_skill_package"]}
    return CandidateResult(
        method="full_rewrite",
        status="VALID",
        raw_response=_raw_content(raw_response),
        final_ir=value,
        format_repairs=formatted.records,
        structural_result={"valid": True, "errors": [], "skill": rewritten, "diff": diff_skill(current_skill, rewritten)},
        eligible_for_dynamic_validation=True,
        request_records=[_request_record(raw_response)] if _request_record(raw_response) else [],
    )


def blind_semantic_verify(
    root_cause: dict,
    preservation_ir: list[dict] | dict,
    candidate_semantics: dict,
    auditor_client: Any,
    *,
    token_budget: int,
) -> VerifierResult:
    """Run a method-blind seven-field semantic audit with no veto power."""

    preservation = preservation_ir if isinstance(preservation_ir, list) else [preservation_ir]
    # Deliberately construct only the permitted semantic view.  No candidate
    # method, generator label, dynamic score, raw trajectory, or expert state
    # is copied into this context.
    candidate_view = copy.deepcopy(candidate_semantics)
    # The audit sees semantic content, but not the representation/method
    # wrapper or provenance labels.  Removing only these envelope keys keeps
    # the actual proposed semantics available for the seven-field rubric.
    if isinstance(candidate_view, dict):
        for envelope in ("semantic_patch", "full_rewrite"):
            if envelope in candidate_view and len(candidate_view) == 1:
                candidate_view = candidate_view[envelope]
                break
        if isinstance(candidate_view, dict):
            for hidden in ("method", "generator", "generator_label", "dynamic_score", "validation_score"):
                candidate_view.pop(hidden, None)
            if "rewritten_skill_package" in candidate_view:
                candidate_view["candidate_skill_package"] = candidate_view.pop("rewritten_skill_package")
            if "change_manifest" in candidate_view:
                candidate_view["changes"] = candidate_view.pop("change_manifest")
    context = {
        "root_cause": copy.deepcopy(root_cause),
        "preservation": copy.deepcopy(preservation),
        "candidate": candidate_view,
        "rubric_fields": list(SEMANTIC_FIELDS),
    }
    raw = auditor_client.complete_meta("semantic_verifier", context, token_budget)
    content = _raw_content(raw)
    try:
        value = normalize_json_response(content)
        scores: dict[str, float] = {}
        for field_name in SEMANTIC_FIELDS:
            score = value.get(field_name)
            if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= float(score) <= 1:
                raise ValueError(f"{field_name} must be a number between 0 and 1")
            scores[field_name] = float(score)
        return VerifierResult(
            scores=scores,
            eligible_for_dynamic_validation=True,
            raw_response=content,
            request_record=_request_record(raw),
            valid=True,
        )
    except (TypeError, ValueError) as exc:
        # A malformed audit is recorded, but cannot veto a structurally valid
        # candidate.  The caller keeps eligible_for_dynamic_validation=True.
        return VerifierResult(
            scores={},
            eligible_for_dynamic_validation=True,
            raw_response=content,
            request_record=_request_record(raw),
            valid=False,
            error=str(exc),
        )


__all__ = [
    "CandidateResult",
    "SEMANTIC_FIELDS",
    "VerifierResult",
    "blind_semantic_verify",
    "verify_rewrite_candidate",
    "verify_structured_candidate",
]
