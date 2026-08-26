"""Dependency-light, deterministic primitives for ALFWorld Stage 0.

The module deliberately contains no ALFWorld, model, or network integration.
It owns the representation contract so that sampling, patching, rendering,
and structural checks remain testable on a machine without the environment.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = "0.1"
NODE_TYPES = {"action", "decision", "verification", "terminal"}
SCOPE_LEVELS = {"global", "task_family", "workflow", "local"}
FAMILIES = {
    "pick_and_place",
    "examine_in_light",
    "clean_and_place",
    "heat_and_place",
    "cool_and_place",
    "pick_two_and_place",
}
# Keep these prefixes exact.  In particular, examine-in-light is not a
# pick-and-place task even though both are object-oriented ALFWorld goals.
TASK_PREFIXES = {
    "pick_and_place": "pick_and_place_simple-",
    "examine_in_light": "look_at_obj_in_light-",
    "clean_and_place": "pick_clean_then_place_in_recep-",
    "heat_and_place": "pick_heat_then_place_in_recep-",
    "cool_and_place": "pick_cool_then_place_in_recep-",
    "pick_two_and_place": "pick_two_obj_and_place-",
}
# Historical ALFWorld runs use all of these split directory names.  A
# canonical task ID intentionally drops the split marker so a train task and
# the same task recorded from another machine cannot evade exact denylisting.
ALFWORLD_SPLIT_MARKERS = {
    "train",
    "valid_train",
    "valid_seen",
    "valid_unseen",
    "test",
    "dev",
    "validation",
}
OPS = {"ADD", "UPDATE", "DELETE"}
KINDS = {"NODE", "EDGE", "CONSTRAINT", "VERIFICATION", "FALLBACK"}
DIFF_KINDS = KINDS | {"PACKAGE"}
_COMPONENTS = (
    ("NODE", "nodes"),
    ("EDGE", "edges"),
    ("CONSTRAINT", "constraints"),
    ("VERIFICATION", "verifications"),
    ("FALLBACK", "fallbacks"),
)
_MISSING = object()


def canonical(value: Any) -> str:
    """Return the stable JSON representation used for semantic comparison."""

    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha256(value: Any) -> str:
    """Hash bytes/text as bytes and structured values as canonical JSON.

    The previous implementation JSON-serialized strings before hashing.  That
    made a rendered-file hash differ from the SHA-256 of the bytes on disk.
    Strings now intentionally mean UTF-8 text; callers hashing structured IR
    still get the canonical JSON behavior.
    """

    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
    elif isinstance(value, str):
        raw = value.encode("utf-8")
    else:
        raw = canonical(value).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: str | Path) -> str:
    """Hash the exact bytes of a file."""

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _ids(items: Iterable[Any], name: str, errors: list[str]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for item in items:
        if not isinstance(item, dict):
            errors.append(f"{name} item must be an object")
            continue
        ident = item.get("id")
        if not _nonempty_string(ident):
            errors.append(f"{name} item has invalid id")
        elif ident in result:
            errors.append(f"duplicate {name} id: {ident}")
        else:
            result[ident] = item
    return result


def _list_field(package: dict, key: str, errors: list[str]) -> list[Any]:
    if key not in package:
        errors.append(f"missing {key}")
        return []
    value = package[key]
    if not isinstance(value, list):
        errors.append(f"{key} must be a list")
        return []
    return value


def _validate_scope(scope: Any, owner: str, node_map: dict[str, dict], errors: list[str]) -> None:
    """Validate the complete scope contract for every scoped artifact."""

    if not isinstance(scope, dict) or not scope:
        errors.append(f"missing or empty scope: {owner}")
        return
    level = scope.get("level")
    if level == "instance":
        errors.append(f"instance scope forbidden: {owner}")
        return
    if level not in SCOPE_LEVELS:
        errors.append(f"invalid scope level: {owner}")
        return
    if level == "task_family":
        target = scope.get("target")
        if target not in FAMILIES:
            errors.append(f"invalid task_family scope: {owner}")
    elif level == "local":
        target = scope.get("target")
        if not _nonempty_string(target) or target not in node_map:
            errors.append(f"local scope target must reference an existing node: {owner}")
    elif "target" in scope and not _nonempty_string(scope.get("target")):
        errors.append(f"scope target must be a non-empty string: {owner}")


def validate_skill(
    skill: dict,
    *,
    max_words: int = 1200,
    enforce_budget: bool = False,
    min_workflow_nodes: int = 6,
    max_workflow_nodes: int = 12,
    max_items_per_artifact: int = 8,
) -> list[str]:
    """Return structural errors for a Skill Package.

    Small fixtures are useful for unit tests, so component budgets are opt-in.
    Production S0 and candidates must call this with ``enforce_budget=True``.
    """

    errors: list[str] = []
    if not isinstance(skill, dict) or set(skill) != {"skill_package"}:
        return ["root must contain only skill_package"]
    package = skill["skill_package"]
    if not isinstance(package, dict):
        return ["skill_package must be an object"]
    if package.get("schema_version") != SCHEMA_VERSION:
        errors.append("unsupported schema_version")
    if not _nonempty_string(package.get("package_id")):
        errors.append("package_id must be a non-empty string")
    if not _nonempty_string(package.get("entry_node")):
        errors.append("entry_node must be a non-empty string")

    nodes = _list_field(package, "nodes", errors)
    edges = _list_field(package, "edges", errors)
    constraints = _list_field(package, "constraints", errors)
    verifications = _list_field(package, "verifications", errors)
    fallbacks = _list_field(package, "fallbacks", errors)

    if not nodes:
        errors.append("nodes must be a non-empty list")
    node_map = _ids(nodes, "node", errors)
    edge_map = _ids(edges, "edge", errors)
    constraint_map = _ids(constraints, "constraint", errors)
    verification_map = _ids(verifications, "verification", errors)
    fallback_map = _ids(fallbacks, "fallback", errors)

    # IDs are also globally unique: an ambiguous cross-kind reference is not
    # safe to inject into an executor prompt.
    seen_ids: dict[str, str] = {}
    for kind, items in (
        ("node", nodes),
        ("edge", edges),
        ("constraint", constraints),
        ("verification", verifications),
        ("fallback", fallbacks),
    ):
        for item in items:
            if not isinstance(item, dict) or not _nonempty_string(item.get("id")):
                continue
            ident = item["id"]
            previous = seen_ids.get(ident)
            if previous is not None and previous != kind:
                errors.append(f"duplicate id across artifacts: {ident}")
            else:
                seen_ids[ident] = kind

    if package.get("entry_node") not in node_map:
        errors.append("entry_node does not exist")

    for node in nodes:
        if not isinstance(node, dict):
            continue
        if node.get("type") not in NODE_TYPES:
            errors.append(f"invalid node type: {node.get('id')}")
        if not _nonempty_string(node.get("instruction")):
            errors.append(f"node instruction must be non-empty: {node.get('id')}")
        _validate_scope(node.get("scope"), f"node {node.get('id')}", node_map, errors)

    for edge in edges:
        if not isinstance(edge, dict):
            continue
        if edge.get("source") not in node_map or edge.get("target") not in node_map:
            errors.append(f"dangling edge: {edge.get('id')}")
        if not _nonempty_string(edge.get("condition")):
            errors.append(f"edge condition must be non-empty: {edge.get('id')}")

    outgoing = {ident: [] for ident in node_map}
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        source, target = edge.get("source"), edge.get("target")
        if source in outgoing and target in node_map:
            outgoing[source].append(target)
    reachable: set[str] = set()
    todo = [package.get("entry_node")]
    while todo:
        node = todo.pop()
        if node in reachable or node not in node_map:
            continue
        reachable.add(node)
        todo.extend(outgoing[node])
    errors.extend(f"unreachable node: {ident}" for ident in node_map if ident not in reachable)

    for constraint in constraints:
        if not isinstance(constraint, dict):
            continue
        if not _nonempty_string(constraint.get("rule")):
            errors.append(f"constraint rule must be non-empty: {constraint.get('id')}")
        _validate_scope(constraint.get("scope"), f"constraint {constraint.get('id')}", node_map, errors)

    for verification in verifications:
        if not isinstance(verification, dict):
            continue
        if verification.get("target") not in node_map or verification.get("on_failure") not in fallback_map:
            errors.append(f"invalid verification reference: {verification.get('id')}")
        if not _nonempty_string(verification.get("criterion")):
            errors.append(f"verification criterion must be non-empty: {verification.get('id')}")
        _validate_scope(verification.get("scope"), f"verification {verification.get('id')}", node_map, errors)

    for fallback in fallbacks:
        if not isinstance(fallback, dict):
            continue
        retries = fallback.get("max_retries")
        if (
            fallback.get("target") not in node_map
            or not isinstance(retries, int)
            or isinstance(retries, bool)
            or retries < 0
        ):
            errors.append(f"invalid fallback: {fallback.get('id')}")
        if not _nonempty_string(fallback.get("trigger")):
            errors.append(f"fallback trigger must be non-empty: {fallback.get('id')}")
        _validate_scope(fallback.get("scope"), f"fallback {fallback.get('id')}", node_map, errors)

    # Keep variables referenced above explicit; this also documents that all
    # collections, including constraints and fallback references, are checked.
    del edge_map, constraint_map, verification_map

    if enforce_budget:
        workflow_count = len(nodes)
        if not min_workflow_nodes <= workflow_count <= max_workflow_nodes:
            errors.append(
                f"workflow node budget must be {min_workflow_nodes}-{max_workflow_nodes}, got {workflow_count}"
            )
        for label, items in (
            ("constraints", constraints),
            ("verifications", verifications),
            ("fallbacks", fallbacks),
        ):
            if len(items) > max_items_per_artifact:
                errors.append(f"{label} exceed budget of {max_items_per_artifact}")
        try:
            word_count = len(re.findall(r"\b[\w'-]+\b", render_skill(skill)))
        except (AttributeError, KeyError, TypeError):
            word_count = max_words + 1
        if word_count > max_words:
            errors.append("rendered skill exceeds word budget")
    return errors


def render_skill(skill: dict) -> str:
    """Render every package condition through one deterministic text contract."""

    package = skill["skill_package"]
    lines = [
        f"SKILL PACKAGE {package.get('package_id', '')} schema={package.get('schema_version')}",
        f"ENTRY: {package.get('entry_node')}",
        "WORKFLOW:",
    ]
    for node in package.get("nodes", []):
        lines.append(
            f"- NODE {node.get('id')} [{node.get('type')}] "
            f"scope={canonical(node.get('scope', {}))}: {node.get('instruction', '')}"
        )
    for edge in package.get("edges", []):
        lines.append(
            f"- EDGE {edge.get('id')}: {edge.get('source')} -> {edge.get('target')} "
            f"when {edge.get('condition', '')}"
        )
    lines.append("CONSTRAINTS:")
    for item in package.get("constraints", []):
        lines.append(
            f"- {item.get('id')} scope={canonical(item.get('scope', {}))}: {item.get('rule', '')}"
        )
    lines.append("VERIFICATIONS:")
    for item in package.get("verifications", []):
        lines.append(
            f"- {item.get('id')} target={item.get('target')} "
            f"if_failed={item.get('on_failure')} scope={canonical(item.get('scope', {}))}: "
            f"{item.get('criterion', '')}"
        )
    lines.append("FALLBACKS:")
    for item in package.get("fallbacks", []):
        lines.append(
            f"- {item.get('id')} target={item.get('target')} retries={item.get('max_retries')} "
            f"scope={canonical(item.get('scope', {}))}: {item.get('trigger', '')}"
        )
    return "\n".join(lines) + "\n"


def _bucket(package: dict, kind: str) -> list[dict]:
    key = dict(_COMPONENTS)[kind]
    return package[key]


def _patch_error(message: str) -> ValueError:
    return ValueError(f"invalid semantic patch: {message}")


def _addresses_only_root(addresses: Any, root_cause_id: str) -> bool:
    return (
        isinstance(addresses, list)
        and addresses == [root_cause_id]
    )


def apply_patch(skill: dict, patch: dict, root_cause_id: str, *, enforce_budget: bool = False) -> dict:
    """Apply a fail-closed, single-root-cause patch without mutating input."""

    if not _nonempty_string(root_cause_id):
        raise _patch_error("root_cause_id must be non-empty")
    if not isinstance(skill, dict):
        raise _patch_error("skill must be an object")
    before_snapshot = canonical(skill)
    base_errors = validate_skill(skill, enforce_budget=False)
    if base_errors:
        raise _patch_error("base skill invalid: " + "; ".join(base_errors))
    if not isinstance(patch, dict):
        raise _patch_error("patch must be an object")
    query = patch.get("semantic_patch", patch)
    if not isinstance(query, dict):
        raise _patch_error("semantic_patch must be an object")
    binding = query.get("diagnosis_binding")
    if not isinstance(binding, dict) or binding.get("root_cause_id") != root_cause_id:
        raise _patch_error("diagnosis_binding is not bound to selected root cause")
    edits = query.get("edits")
    if not isinstance(edits, list) or not edits:
        raise _patch_error("edits must be a non-empty list")

    out = copy.deepcopy(skill)
    package = out["skill_package"]
    for edit in edits:
        if not isinstance(edit, dict):
            raise _patch_error("each edit must be an object")
        addresses = edit.get("addresses")
        if not _addresses_only_root(addresses, root_cause_id):
            raise _patch_error("each edit needs non-empty addresses containing only the selected root cause")
        op, kind = edit.get("op"), edit.get("kind")
        if op not in OPS or kind not in KINDS:
            raise _patch_error("invalid patch operation or kind")
        items = _bucket(package, kind)

        if op == "ADD":
            value = edit.get("value")
            if not isinstance(value, dict) or not _nonempty_string(value.get("id")):
                raise _patch_error("ADD value must be an object with a non-empty id")
            if "target_id" in edit and edit.get("target_id") != value.get("id"):
                raise _patch_error("ADD target_id must match value.id")
            ident = value["id"]
            if any(isinstance(item, dict) and item.get("id") == ident for item in items):
                raise _patch_error(f"ADD existing id: {ident}")
            items.append(copy.deepcopy(value))
            continue

        target_id = edit.get("target_id")
        if not _nonempty_string(target_id):
            raise _patch_error(f"{op} requires a non-empty target_id")
        matches = [index for index, item in enumerate(items) if isinstance(item, dict) and item.get("id") == target_id]
        if len(matches) != 1:
            raise _patch_error(f"{op} target must identify exactly one existing item: {target_id}")
        index = matches[0]
        if op == "UPDATE":
            value = edit.get("value")
            if not isinstance(value, dict) or value.get("id") != target_id:
                raise _patch_error("UPDATE value must be an object whose id equals target_id")
            items[index] = copy.deepcopy(value)
        else:  # DELETE
            if "value" in edit and edit.get("value") not in (None, {}):
                raise _patch_error("DELETE cannot carry a non-empty value")
            del items[index]

    # Validate the result before returning and prove the caller-owned input was
    # not changed by any branch above.
    errors = validate_skill(out, enforce_budget=enforce_budget)
    if errors:
        raise _patch_error("patched skill invalid: " + "; ".join(errors))
    if canonical(skill) != before_snapshot:
        raise _patch_error("input skill was mutated")
    return out


def _component_map(package: dict, key: str) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for item in package.get(key, []):
        if isinstance(item, dict) and _nonempty_string(item.get("id")):
            result[item["id"]] = item
    return result


def diff_skill(before: dict, after: dict) -> list[dict]:
    """Return the deterministic canonical IR diff, including package fields."""

    before_package = before["skill_package"]
    after_package = after["skill_package"]
    result: list[dict] = []

    package_keys = sorted(
        (set(before_package) | set(after_package)) - {key for _, key in _COMPONENTS}
    )
    for key in package_keys:
        old = before_package.get(key, _MISSING)
        new = after_package.get(key, _MISSING)
        if old is _MISSING or new is _MISSING or canonical(old) != canonical(new):
            result.append({"change": "UPDATE", "kind": "PACKAGE", "target_id": key})

    for kind, key in _COMPONENTS:
        old_map = _component_map(before_package, key)
        new_map = _component_map(after_package, key)
        for ident in sorted(old_map.keys() - new_map.keys()):
            result.append({"change": "DELETE", "kind": kind, "target_id": ident})
        for ident in sorted(new_map.keys() - old_map.keys()):
            result.append({"change": "ADD", "kind": kind, "target_id": ident})
        for ident in sorted(old_map.keys() & new_map.keys()):
            if canonical(old_map[ident]) != canonical(new_map[ident]):
                result.append({"change": "UPDATE", "kind": kind, "target_id": ident})
    return result


def _validate_change_manifest(
    before: dict,
    after: dict,
    manifest: Any,
    root_cause_id: str,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(manifest, list):
        return ["change_manifest must be a list"]
    actual = diff_skill(before, after)
    expected_keys = [(x["change"], x["kind"], x["target_id"]) for x in actual]
    seen: list[tuple[str, str, str]] = []
    for item in manifest:
        if not isinstance(item, dict):
            errors.append("change_manifest item must be an object")
            continue
        change, kind, target = item.get("change"), item.get("kind"), item.get("target_id")
        if change not in OPS or kind not in DIFF_KINDS or not _nonempty_string(target):
            errors.append("change_manifest item has invalid change/kind/target_id")
            continue
        addresses = item.get("addresses")
        if not _addresses_only_root(addresses, root_cause_id):
            errors.append(f"change_manifest entry {target} has invalid addresses")
        key = (change, kind, target)
        if key in seen:
            errors.append(f"duplicate change_manifest entry: {key}")
        seen.append(key)
    if sorted(seen) != sorted(expected_keys):
        errors.append(
            "change_manifest does not equal canonical IR diff: "
            f"declared={sorted(seen)!r} actual={sorted(expected_keys)!r}"
        )
    return errors


def validate_full_rewrite(
    before: dict,
    rewrite: dict,
    root_cause_id: str,
    *,
    enforce_budget: bool = False,
) -> list[str]:
    """Validate a Full Rewrite envelope and its exact, bound IR diff."""

    errors: list[str] = []
    if not _nonempty_string(root_cause_id):
        errors.append("root_cause_id must be non-empty")
    if not isinstance(rewrite, dict):
        return ["full_rewrite must be an object"]
    query = rewrite.get("full_rewrite", rewrite)
    if not isinstance(query, dict):
        return ["full_rewrite must be an object"]
    binding = query.get("diagnosis_binding")
    if not isinstance(binding, dict) or binding.get("root_cause_id") != root_cause_id:
        errors.append("diagnosis_binding is not bound to selected root cause")
    after = query.get("rewritten_skill_package")
    if not isinstance(after, dict):
        return errors + ["rewritten_skill_package must be an object"]
    wrapped = {"skill_package": after}
    errors.extend(validate_skill(wrapped, enforce_budget=enforce_budget))
    errors.extend(_validate_change_manifest(before, wrapped, query.get("change_manifest"), root_cause_id))
    return errors


def validate_change_manifest(before: dict, after: dict, manifest: Any, root_cause_id: str) -> list[str]:
    """Public helper for tests and callers that already unwrapped a rewrite."""

    return _validate_change_manifest(before, after, manifest, root_cause_id)


def canonical_task_id(value: str | Path, *, train_root: str | Path | None = None) -> str:
    """Canonicalize a task ID without machine-specific absolute prefixes.

    A task ID is a relative ``game.tw-pddl`` path under the selected train
    root.  For historical absolute IDs, recognizable ``train`` or
    ``json_2.1.1/<split>`` markers are retained as a stable relative prefix.
    Separators are normalized here; case folding is deliberately left to
    comparison helpers.
    """

    if not isinstance(value, (str, Path)):
        raise ValueError("task ID must be a string or path")
    raw = str(value).strip().replace("\\", "/")
    if not raw:
        raise ValueError("task ID must be non-empty")
    raw = re.sub(r"^\./+", "", raw)
    def strip_split_marker(path_parts: list[str]) -> str | None:
        marker_indices = [
            index for index, part in enumerate(path_parts)
            if part.casefold() in ALFWORLD_SPLIT_MARKERS
        ]
        if not marker_indices:
            return None
        index = marker_indices[-1]
        return "/".join(path_parts[index + 1 :]) or None

    root: Path | None = None
    if train_root is not None:
        root = Path(train_root).resolve(strict=False)
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = root / candidate
        try:
            relative = candidate.resolve(strict=False).relative_to(root).as_posix()
            stripped = strip_split_marker(relative.split("/"))
            return stripped if stripped is not None else relative
        except ValueError:
            pass

    parts = [part for part in raw.split("/") if part not in ("", ".")]
    stripped = strip_split_marker(parts)
    if stripped is not None:
        return stripped
    lower = [part.casefold() for part in parts]
    if "json_2.1.1" in lower:
        index = len(lower) - 1 - lower[::-1].index("json_2.1.1")
        if index + 1 < len(parts):
            return "/".join(parts[index + 1 :])
    return "/".join(parts)


def task_id_key(value: str | Path, *, train_root: str | Path | None = None) -> str:
    """Comparison form of a canonical task ID (case-insensitive, slash-stable)."""

    return canonical_task_id(value, train_root=train_root).casefold()


def classify_task_family(path: str | Path) -> str | None:
    """Classify exactly one ALFWorld family from a task path."""

    normalized = str(path).replace("\\", "/").casefold()
    segments = normalized.split("/")
    matches = [
        family
        for family, prefix in TASK_PREFIXES.items()
        if any(segment.startswith(prefix.casefold()) for segment in segments)
    ]
    if len(matches) == 1:
        return matches[0]
    # A direct task-template string is useful in focused tests.
    matches = [family for family, prefix in TASK_PREFIXES.items() if normalized.startswith(prefix.casefold())]
    return matches[0] if len(matches) == 1 else None


def task_group_key(path: str | Path) -> str:
    """Build a trial-independent near-duplicate key from ALFWorld path fields."""

    normalized = canonical_task_id(path)
    segments = normalized.split("/")
    family = classify_task_family(normalized)
    prefix = TASK_PREFIXES.get(family, "")
    template = next(
        (segment for segment in segments if prefix and segment.casefold().startswith(prefix.casefold())),
        next((segment for segment in segments if segment.casefold().startswith("trial_")), ""),
    )
    if prefix and template.casefold().startswith(prefix.casefold()):
        suffix = template[len(prefix) :].split("-")
        if len(suffix) >= 4:
            object_name, movable, receptacle, scene = suffix[-4:]
        else:
            object_name, movable, receptacle, scene = (suffix + ["unknown"] * 4)[-4:]
    else:
        object_name = movable = receptacle = scene = "unknown"
    lower_all = normalized.casefold()
    if "unsliced" in lower_all:
        sliced = "unsliced"
    elif "sliced" in lower_all:
        sliced = "sliced"
    else:
        sliced = "unspecified"
    # Deliberately omit every trial_* segment.  The complete key retains the
    # task type/goal template and all ALFWorld object/receptacle/scene fields.
    goal_template = template.rsplit("-", 1)[0] if template else "unknown"
    return (
        f"task_type={family or 'unknown'}|goal_template={goal_template.casefold()}|"
        f"object={object_name.casefold()}|movable_receptacle={movable.casefold()}|"
        f"target_receptacle={receptacle.casefold()}|scene={scene.casefold()}|sliced={sliced}"
    )


def paired_outcomes(baseline: list[dict], candidate: list[dict]) -> list[dict]:
    """Compute paired outcomes only when both task sets are exact matches."""

    def outcome_map(rows: Any, label: str) -> dict[str, dict]:
        if not isinstance(rows, list):
            raise ValueError(f"{label} outcomes must be a list")
        result: dict[str, dict] = {}
        for row in rows:
            if not isinstance(row, dict) or not _nonempty_string(row.get("task_id")):
                raise ValueError(f"{label} outcome has missing task_id")
            if not isinstance(row.get("success"), bool):
                raise ValueError(f"{label} outcome success must be boolean")
            canonical_id = canonical_task_id(row["task_id"])
            key = canonical_id.casefold()
            if key in result:
                raise ValueError(f"duplicate {label} task_id: {canonical_id}")
            result[key] = {"task_id": canonical_id, "success": row["success"]}
        return result

    baseline_map = outcome_map(baseline, "baseline")
    candidate_map = outcome_map(candidate, "candidate")
    if set(baseline_map) != set(candidate_map):
        missing = sorted(set(baseline_map) - set(candidate_map))
        extra = sorted(set(candidate_map) - set(baseline_map))
        raise ValueError(f"baseline/candidate task sets differ: missing={missing}, extra={extra}")

    rows: list[dict] = []
    for key in sorted(baseline_map):
        baseline_success = baseline_map[key]["success"]
        candidate_success = candidate_map[key]["success"]
        category = (
            "repair"
            if not baseline_success and candidate_success
            else "regression"
            if baseline_success and not candidate_success
            else "stable_success"
            if baseline_success
            else "stable_failure"
        )
        rows.append(
            {
                "task_id": baseline_map[key]["task_id"],
                "baseline_success": baseline_success,
                "candidate_success": candidate_success,
                "category": category,
            }
        )
    counts = Counter(row["category"] for row in rows)
    net_gain = counts["repair"] - counts["regression"]
    rows.append(
        {
            "summary": {
                "repairs": counts["repair"],
                "regressions": counts["regression"],
                "stable_success": counts["stable_success"],
                "stable_failure": counts["stable_failure"],
                "NetGain": net_gain,
                "net_gain": net_gain,
                "n": len(rows),
            }
        }
    )
    return rows
