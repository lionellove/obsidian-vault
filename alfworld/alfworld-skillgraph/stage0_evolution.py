"""Offline-testable Stage 0 evolution orchestration.

This module intentionally stops at structured artifacts and verification.  It
does not execute ALFWorld, consult expert plans, or perform dynamic rollout.
The injected client is the only semantic-generation seam.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any, Iterable

from stage0_core import canonical, validate_skill
from stage0_format import normalize_json_response
from stage0_ir import (
    IRValidationError,
    normalize_failure_ir,
    normalize_preservation_ir,
    normalize_root_cause_candidates,
    validate_root_cause_ir,
)
from stage0_verifier import (
    CandidateResult,
    VerifierResult,
    blind_semantic_verify,
    verify_rewrite_candidate,
    verify_structured_candidate,
)


NO_ROOT_CAUSE = "NO_ROOT_CAUSE"
_HIDDEN_KEYS = {"expert_plan", "expert_trajectory", "pddl_plan", "pddl_state", "hidden_state", "target_location"}


def _content(value: Any) -> Any:
    return getattr(value, "content", value)


def _record(value: Any) -> dict | None:
    candidate = getattr(value, "record", None)
    return copy.deepcopy(candidate) if isinstance(candidate, dict) else None


def _assert_no_hidden(value: Any, path: str = "input") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = str(key).casefold()
            if lowered in _HIDDEN_KEYS or "expert" in lowered or "pddl" in lowered or "hidden_state" in lowered:
                raise ValueError(f"analyzer input firewall rejected hidden field: {path}.{key}")
            _assert_no_hidden(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_no_hidden(child, f"{path}[{index}]")


def _safe_trajectory_fields(record: dict, *, current_skill: dict, outcome: str) -> dict:
    """Build the only analyzer input shape accepted by this pipeline."""

    if not isinstance(record, dict):
        raise ValueError("trajectory must be an object")
    _assert_no_hidden(record)
    _assert_no_hidden(current_skill, "current_skill")
    context = {
        "outcome": outcome,
        "trace_id": record.get("trace_id"),
        "task_id": record.get("task_id"),
        "trajectory": copy.deepcopy(record.get("trajectory", [])),
        "current_skill": copy.deepcopy(current_skill),
        "task_goal": copy.deepcopy(record.get("task_goal", record.get("goal", ""))),
        "admissible_actions": copy.deepcopy(record.get("admissible_actions", record.get("actions", []))),
        "reward": copy.deepcopy(record.get("reward")),
        "termination": copy.deepcopy(record.get("termination")),
    }
    # A test/fake may provide a deterministic failure ID hint.  It is metadata,
    # not hidden execution state, and is useful for binding analyzer output.
    if "failure_id_hint" in record:
        context["failure_id_hint"] = record["failure_id_hint"]
    _assert_no_hidden(context)
    return context


def build_failure_analyzer_context(record: dict, current_skill: dict) -> dict:
    return _safe_trajectory_fields(record, current_skill=current_skill, outcome="failure")


def build_success_analyzer_context(record: dict, current_skill: dict) -> dict:
    return _safe_trajectory_fields(record, current_skill=current_skill, outcome="success")


def _meta(client: Any, role: str, context: Any, token_budget: int) -> Any:
    method = getattr(client, "complete_meta", None)
    if method is None:
        raise TypeError("semantic client must provide complete_meta")
    return method(role=role, context=context, token_budget=token_budget)


def _parse(value: Any) -> dict:
    return normalize_json_response(_content(value))


def _failure_instances(failures: list[dict]) -> dict[str, dict]:
    return {failure["failure_id"]: failure for failure in failures}


class FailureAnalyzer:
    """One semantic Failure IR generation with an input firewall."""

    def __init__(self, client: Any, *, token_budget: int = 2048) -> None:
        self.client = client
        self.token_budget = token_budget
        self.last_request_record: dict | None = None
        self.last_raw_response: Any = None

    def analyze(self, trajectory: dict, current_skill: dict) -> dict:
        context = build_failure_analyzer_context(trajectory, current_skill)
        raw = _meta(self.client, "failure_analyzer", context, self.token_budget)
        self.last_raw_response = _content(raw)
        self.last_request_record = _record(raw)
        failure = normalize_failure_ir(_parse(raw))
        failure.setdefault("trace_id", trajectory.get("trace_id"))
        failure.setdefault("task_id", trajectory.get("task_id"))
        return failure


class SuccessAnalyzer:
    """One semantic Preservation IR generation with an input firewall."""

    def __init__(self, client: Any, *, token_budget: int = 2048) -> None:
        self.client = client
        self.token_budget = token_budget
        self.last_request_record: dict | None = None
        self.last_raw_response: Any = None

    def analyze(self, trajectory: dict, current_skill: dict) -> dict:
        context = build_success_analyzer_context(trajectory, current_skill)
        raw = _meta(self.client, "success_analyzer", context, self.token_budget)
        self.last_raw_response = _content(raw)
        self.last_request_record = _record(raw)
        preservation = normalize_preservation_ir(_parse(raw))
        preservation.setdefault("trace_id", trajectory.get("trace_id"))
        preservation.setdefault("task_id", trajectory.get("task_id"))
        return preservation


class RootCauseMerger:
    """Semantic Root Cause merge plus deterministic eligibility selection."""

    def __init__(self, client: Any, *, token_budget: int = 2048) -> None:
        self.client = client
        self.token_budget = token_budget
        self.last_request_record: dict | None = None
        self.last_raw_response: Any = None

    def merge(self, failures: Iterable[dict], preservations: Iterable[dict] = ()) -> dict:
        failure_values = copy.deepcopy(list(failures))
        preservation_values = copy.deepcopy(list(preservations))
        context = {"failures": failure_values, "preservations": preservation_values}
        _assert_no_hidden(context)
        raw = _meta(self.client, "root_cause_merger", context, self.token_budget)
        self.last_raw_response = _content(raw)
        self.last_request_record = _record(raw)
        candidates = normalize_root_cause_candidates(_parse(raw))
        return select_root_cause(candidates, failure_values)


def select_root_cause(root_causes: Iterable[dict], failures: Iterable[dict]) -> dict:
    """Select the highest-priority patchable, non-contradictory root cause."""

    candidates = list(root_causes)
    failure_values = list(failures)
    failure_map = _failure_instances(failure_values)
    if len(failure_map) != len(failure_values):
        return {"status": NO_ROOT_CAUSE, "reason": "duplicate failure_id in Failure IR"}
    seen: set[str] = set()
    for item in candidates:
        ident = item.get("root_cause_id") if isinstance(item, dict) else None
        if not isinstance(ident, str) or ident in seen:
            return {"status": NO_ROOT_CAUSE, "reason": "duplicate or invalid root_cause_id"}
        seen.add(ident)

    eligible: list[tuple[int, str, dict]] = []
    for item in candidates:
        if validate_root_cause_ir(item):
            continue
        if item.get("patchability") != "skill_patchable":
            continue
        if item.get("contradictory_evidence"):
            continue
        identities: set[tuple[str, str]] = set()
        for ref in item.get("supported_by", []):
            failure = failure_map.get(ref.get("failure_id")) if isinstance(ref, dict) else None
            if failure is None:
                # A Root Cause cannot manufacture support for an analyzer
                # result that was never accepted into this run's Failure IR.
                continue
            trace_id = ref.get("trace_id") if isinstance(ref, dict) else None
            task_id = ref.get("task_id") if isinstance(ref, dict) else None
            if (
                trace_id
                and failure.get("trace_id")
                and trace_id != failure.get("trace_id")
            ):
                continue
            if task_id and failure.get("task_id") and task_id != failure.get("task_id"):
                continue
            if failure:
                trace_id = trace_id or failure.get("trace_id")
                task_id = task_id or failure.get("task_id")
            if isinstance(trace_id, str) and trace_id.strip():
                # A trace itself is the stable fallback instance identifier
                # when an upstream trajectory did not carry task_id metadata.
                identities.add((trace_id, task_id or trace_id))
        if len(identities) >= 2 and item.get("scope", {}).get("level") != "instance":
            priority = item.get("priority")
            eligible.append((priority, item["root_cause_id"], copy.deepcopy(item)))
    if not eligible:
        return {"status": NO_ROOT_CAUSE, "reason": "no root cause met support, scope, patchability, and contradiction gates"}
    eligible.sort(key=lambda row: (row[0], row[1]))
    return eligible[0][2]


def _evidence_context(root_cause: dict, failures: list[dict], preservations: list[dict], current_skill: dict) -> dict:
    failure_map = _failure_instances(failures)
    root_context = copy.deepcopy(root_cause)
    for support in root_context.get("supported_by", []):
        if isinstance(support, dict):
            # Task/game paths are instance identifiers.  Trace/step refs are
            # retained because they are the auditable minimal evidence link.
            support.pop("task_id", None)
    preservation_context = copy.deepcopy(preservations)
    for preservation in preservation_context:
        if isinstance(preservation, dict):
            preservation.pop("task_id", None)
    snippets: list[dict] = []
    refs: list[dict] = []
    for ref in root_cause.get("supported_by", []):
        failure = failure_map.get(ref.get("failure_id"))
        evidence = failure.get("evidence", {}) if failure else {}
        snippets.append(
            {
                "observation": evidence.get("observation", ""),
                "expected_semantics": evidence.get("expected_semantics", ""),
                "cause": failure.get("cause", "") if failure else "",
            }
        )
        refs.append(
            {
                "trace_id": ref.get("trace_id"),
                "trajectory_steps": copy.deepcopy(ref.get("trajectory_steps", evidence.get("trajectory_steps", []))),
            }
        )
    # Explicitly serialize the same current S for both generators.  The JSON
    # is their byte-identical semantic input, not a pretty-rendered variant.
    return {
        "current_skill_json": canonical(current_skill),
        "root_cause": root_context,
        "preservation_ir": preservation_context,
        "evidence_snippets": snippets,
        "support_refs": refs,
    }


@dataclass
class EvolutionResult:
    failures: list[dict] = field(default_factory=list)
    preservations: list[dict] = field(default_factory=list)
    root_cause: dict = field(default_factory=lambda: {"status": NO_ROOT_CAUSE})
    structured_candidate: CandidateResult | None = None
    rewrite_candidate: CandidateResult | None = None
    structured_verifier: VerifierResult | None = None
    rewrite_verifier: VerifierResult | None = None
    request_records: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def selected_root_cause(self) -> dict | None:
        return None if self.root_cause.get("status") == NO_ROOT_CAUSE else self.root_cause

    def to_dict(self) -> dict:
        return {
            "failures": copy.deepcopy(self.failures),
            "preservations": copy.deepcopy(self.preservations),
            "root_cause": copy.deepcopy(self.root_cause),
            "structured_candidate": self.structured_candidate.to_dict() if self.structured_candidate else None,
            "rewrite_candidate": self.rewrite_candidate.to_dict() if self.rewrite_candidate else None,
            "structured_verifier": self.structured_verifier.to_dict() if self.structured_verifier else None,
            "rewrite_verifier": self.rewrite_verifier.to_dict() if self.rewrite_verifier else None,
            "request_records": copy.deepcopy(self.request_records),
            "errors": list(self.errors),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "EvolutionResult":
        """Rehydrate a frozen semantic stage without another model request."""

        if not isinstance(value, dict):
            raise ValueError("EvolutionResult artifact must be an object")

        def candidate(raw: Any) -> CandidateResult | None:
            if not isinstance(raw, dict):
                return None
            return CandidateResult(
                method=str(raw.get("method", "")),
                status=str(raw.get("status", "INVALID")),
                raw_response=raw.get("raw_response"),
                final_ir=raw.get("final_ir"),
                format_repairs=list(raw.get("format_repairs", [])),
                structural_result=raw.get("structural_result"),
                eligible_for_dynamic_validation=bool(raw.get("eligible_for_dynamic_validation", False)),
                request_records=list(raw.get("request_records", [])),
                error=raw.get("error"),
            )

        def verifier(raw: Any) -> VerifierResult | None:
            if not isinstance(raw, dict):
                return None
            return VerifierResult(
                scores=dict(raw.get("scores", {})),
                eligible_for_dynamic_validation=bool(raw.get("eligible_for_dynamic_validation", True)),
                raw_response=raw.get("raw_response"),
                request_record=raw.get("request_record"),
                valid=bool(raw.get("valid", True)),
                error=raw.get("error"),
            )

        return cls(
            failures=list(value.get("failures", [])),
            preservations=list(value.get("preservations", [])),
            root_cause=dict(value.get("root_cause", {"status": NO_ROOT_CAUSE})),
            structured_candidate=candidate(value.get("structured_candidate")),
            rewrite_candidate=candidate(value.get("rewrite_candidate")),
            structured_verifier=verifier(value.get("structured_verifier")),
            rewrite_verifier=verifier(value.get("rewrite_verifier")),
            request_records=list(value.get("request_records", [])),
            errors=list(value.get("errors", [])),
        )


class EvolutionEngine:
    """Run the analyzer → merger → dual-generator → audit pipeline once."""

    def __init__(
        self,
        client: Any,
        *,
        token_budget: int = 2048,
        repairer: Any = None,
        verifier_client: Any = None,
        enforce_budget: bool = True,
    ) -> None:
        if isinstance(token_budget, bool) or not isinstance(token_budget, int) or token_budget <= 0:
            raise ValueError("token_budget must be a positive integer")
        self.client = client
        self.token_budget = token_budget
        self.repairer = repairer
        self.verifier_client = verifier_client or client
        self.enforce_budget = bool(enforce_budget)

    def _analyze_failures(self, records: list[dict], current_skill: dict, result: EvolutionResult) -> None:
        for record in records:
            context = build_failure_analyzer_context(record, current_skill)
            try:
                raw = _meta(self.client, "failure_analyzer", context, self.token_budget)
                failure = normalize_failure_ir(_parse(raw))
                # Provenance is owned by the observed trajectory row.  A
                # model/fake cannot manufacture a supporting trace or task
                # identity in its Failure IR response.
                failure["trace_id"] = record.get("trace_id")
                failure["task_id"] = record.get("task_id")
                result.failures.append(failure)
                if _record(raw):
                    result.request_records.append(_record(raw))
            except (IRValidationError, TypeError, ValueError, KeyError) as exc:
                result.errors.append(f"failure analyzer rejected {record.get('trace_id')}: {exc}")

    def _analyze_successes(self, records: list[dict], current_skill: dict, result: EvolutionResult) -> None:
        for record in records:
            context = build_success_analyzer_context(record, current_skill)
            try:
                raw = _meta(self.client, "success_analyzer", context, self.token_budget)
                preservation = normalize_preservation_ir(_parse(raw))
                preservation["trace_id"] = record.get("trace_id")
                preservation["task_id"] = record.get("task_id")
                result.preservations.append(preservation)
                if _record(raw):
                    result.request_records.append(_record(raw))
            except (IRValidationError, TypeError, ValueError, KeyError) as exc:
                result.errors.append(f"success analyzer rejected {record.get('trace_id')}: {exc}")

    def run(self, trajectories: Iterable[dict], current_skill: dict) -> EvolutionResult:
        if not isinstance(trajectories, Iterable) or isinstance(trajectories, (str, bytes, dict)):
            raise ValueError("trajectories must be an iterable of trajectory objects")
        skill_errors = validate_skill(current_skill, enforce_budget=self.enforce_budget)
        if skill_errors:
            raise ValueError("current skill is structurally invalid: " + "; ".join(skill_errors))
        records = [copy.deepcopy(item) for item in trajectories]
        if any(not isinstance(item, dict) for item in records):
            raise ValueError("each trajectory must be an object")
        if any(not isinstance(item.get("success"), bool) for item in records):
            raise ValueError("each trajectory must declare boolean success")
        _assert_no_hidden(records)
        result = EvolutionResult()
        failures = [item for item in records if item.get("success") is False]
        successes = [item for item in records if item.get("success") is True]
        self._analyze_failures(failures, current_skill, result)
        self._analyze_successes(successes, current_skill, result)

        if len(result.failures) != len(failures):
            result.root_cause = {"status": NO_ROOT_CAUSE, "reason": "one or more Failure IR records were invalid"}
            return result
        if len(result.preservations) != len(successes):
            result.root_cause = {"status": NO_ROOT_CAUSE, "reason": "one or more Preservation IR records were invalid"}
            return result
        if not result.failures:
            result.root_cause = {"status": NO_ROOT_CAUSE, "reason": "no failed trajectories"}
            return result

        merger_context = {
            "failures": copy.deepcopy(result.failures),
            "preservations": copy.deepcopy(result.preservations),
        }
        try:
            merger_raw = _meta(self.client, "root_cause_merger", merger_context, self.token_budget)
            root_candidates = normalize_root_cause_candidates(_parse(merger_raw))
            result.root_cause = select_root_cause(root_candidates, result.failures)
            if _record(merger_raw):
                result.request_records.append(_record(merger_raw))
        except (IRValidationError, TypeError, ValueError, KeyError) as exc:
            result.root_cause = {"status": NO_ROOT_CAUSE, "reason": f"root cause merger rejected output: {exc}"}
            result.errors.append(str(exc))
            return result

        if result.root_cause.get("status") == NO_ROOT_CAUSE:
            return result

        generation_context = _evidence_context(result.root_cause, result.failures, result.preservations, current_skill)
        # Keep the object semantically identical for both generators.  The
        # role is the only generation-side distinction and is not included in
        # the context supplied to either model.
        structured_raw = _meta(self.client, "structured_patch", generation_context, self.token_budget)
        rewrite_raw = _meta(self.client, "full_rewrite", generation_context, self.token_budget)
        result.structured_candidate = verify_structured_candidate(
            current_skill,
            structured_raw,
            result.root_cause["root_cause_id"],
            self.repairer,
            enforce_budget=self.enforce_budget,
        )
        result.rewrite_candidate = verify_rewrite_candidate(
            current_skill,
            rewrite_raw,
            result.root_cause["root_cause_id"],
            self.repairer,
            enforce_budget=self.enforce_budget,
        )
        for raw in (structured_raw, rewrite_raw):
            if _record(raw):
                result.request_records.append(_record(raw))

        if result.structured_candidate.valid:
            result.structured_verifier = blind_semantic_verify(
                result.root_cause,
                result.preservations,
                result.structured_candidate.final_ir or {},
                self.verifier_client,
                token_budget=self.token_budget,
            )
            if result.structured_verifier.request_record:
                result.request_records.append(copy.deepcopy(result.structured_verifier.request_record))
        if result.rewrite_candidate.valid:
            result.rewrite_verifier = blind_semantic_verify(
                result.root_cause,
                result.preservations,
                result.rewrite_candidate.final_ir or {},
                self.verifier_client,
                token_budget=self.token_budget,
            )
            if result.rewrite_verifier.request_record:
                result.request_records.append(copy.deepcopy(result.rewrite_verifier.request_record))
        return result


__all__ = [
    "EvolutionEngine",
    "EvolutionResult",
    "FailureAnalyzer",
    "NO_ROOT_CAUSE",
    "RootCauseMerger",
    "SuccessAnalyzer",
    "build_failure_analyzer_context",
    "build_success_analyzer_context",
    "select_root_cause",
]
