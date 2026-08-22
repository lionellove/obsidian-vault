"""Family-level SkillGraph experiment orchestration for AutomationBench.

The module keeps optimizer-visible data separate from sealed evaluator data.  Its
pure interfaces are also used by the live CLI so the experiment contract can be
tested without making model calls.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import inspect
import json
import os
import random
import re
import statistics
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence


ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
AUTOMATIONBENCH_ROOT = REPO_ROOT / "AutomationBench"
sys.path.insert(0, str(AUTOMATIONBENCH_ROOT))

from automationbench.domains import get_domain_dataset  # noqa: E402
from automationbench import tools as automationbench_tools  # noqa: E402
from automationbench.skillgraph_runtime import (  # noqa: E402
    GraphRuntime,  # noqa: F401 - public re-export for experiment tests/consumers
    apply_atomic_edit,
    minimal_graph,
    validate_graph,
)


FAMILY_ID = "hr-policy-governed-spreadsheet-batch-v1"
SPLIT_SALT = "skillgraph-family-v1:"
FAMILY_TOOLS = (
    "gmail_find_email",
    "gmail_get_email_by_id",
    "gmail_send_email",
    "google_sheets_find_worksheet",
    "google_sheets_get_many_rows",
    "google_sheets_get_spreadsheet_by_id",
    "google_sheets_update_row",
    "slack_send_channel_message",
)
SPLIT_SIZES = {"train": 12, "validation": 5, "test": 8}
TRAIN_BATCH_SIZES = (3, 3, 2, 2, 2)
SUPPORTED_EDIT_OPERATORS = frozenset(
    {
        "NO_EDIT",
        "UPDATE_NODE",
        "INSERT_NODE",
        "DELETE_NODE",
        "SPLIT_NODE",
        "INTRODUCE_BRANCH",
        "ADD_VERIFICATION",
        "ADD_BOUNDED_RETRY",
        "ADD_FALLBACK",
    }
)
AUTHOR_MODEL = "deepseek-v4-flash"
ARMS = (
    "no-skill",
    "per-task-static-markdown",
    "family-static-markdown",
    "family-incremental-markdown",
    "one-shot-family-skillgraph",
    "batch-refine-skillgraph",
    "incremental-skillgraph",
)


def _tool_signatures(names: Sequence[str]) -> list[dict[str, str]]:
    signatures = []
    for name in names:
        tool = getattr(automationbench_tools, name)
        signatures.append(
            {
                "name": name,
                "signature": f"{name}{inspect.signature(tool)}",
                "description": inspect.getdoc(tool) or "",
            }
        )
    return signatures


def _task_info(row: Mapping[str, Any]) -> dict[str, Any]:
    info = row.get("info", {})
    if isinstance(info, str):
        info = json.loads(info)
    if not isinstance(info, dict):
        raise TypeError("Task info must be a mapping or serialized mapping")
    return info


def _task_request(row: Mapping[str, Any]) -> str:
    prompt = row.get("prompt", [])
    if isinstance(prompt, str):
        prompt = json.loads(prompt)
    if not isinstance(prompt, list):
        raise TypeError("Task prompt must be a message list")
    parts = [
        str(message.get("content") or "")
        for message in prompt
        if isinstance(message, dict) and message.get("role") == "user"
    ]
    parts = [part for part in parts if part]
    if not parts:
        raise ValueError(f"Task {row.get('task')!r} has no public user request")
    return "\n\n".join(parts)


def _merge_shapes(left: Any, right: Any) -> Any:
    if left == right:
        return left
    if isinstance(left, dict) and isinstance(right, dict):
        merged = dict(left)
        for key, value in right.items():
            merged[key] = _merge_shapes(merged[key], value) if key in merged else value
        return merged
    if isinstance(left, list) and isinstance(right, list):
        if not left:
            return right
        if not right:
            return left
        return [_merge_shapes(left[0], right[0])]
    alternatives = set()
    for value in (left, right):
        if isinstance(value, str):
            alternatives.add(value)
        elif isinstance(value, dict) and set(value) == {"one_of"}:
            alternatives.update(value["one_of"])
        else:
            alternatives.add(json.dumps(value, sort_keys=True))
    return {"one_of": sorted(alternatives)}


def state_schema(value: Any) -> Any:
    """Return a deterministic key/type schema with no primitive instance values."""
    if isinstance(value, dict):
        return {str(key): state_schema(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        if not value:
            return []
        shape = state_schema(value[0])
        for item in value[1:]:
            shape = _merge_shapes(shape, state_schema(item))
        return [shape]
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    return "string"


def build_task_card(task: Mapping[str, Any]) -> dict[str, Any]:
    """Build the assertion-free, instance-free authoring view for one task."""
    tools = task.get("available_tools", [])
    if isinstance(tools, dict):
        tools = tools.get("discoverable_operation_hints", tools)
    state = task.get("initial_state", {})
    source_labels = {
        "gmail": "email",
        "google_sheets": "spreadsheet",
        "slack": "chat",
    }
    return {
        "task_id": str(task["task_id"]),
        "task_request": str(task["task_request"]),
        "available_tools": copy.deepcopy(tools),
        "state_schema": state_schema(state),
        "policy_source_types": [
            label for service, label in source_labels.items() if service in state
        ],
    }


def _family_rows() -> list[dict[str, Any]]:
    dataset = get_domain_dataset("hr")
    selected: list[dict[str, Any]] = []
    target_tools = tuple(sorted(FAMILY_TOOLS))
    for index in range(len(dataset)):
        row = dataset[index]
        info = _task_info(row)
        if tuple(sorted(info.get("zapier_tools", []))) != target_tools:
            continue
        task_id = str(row["task"])
        selected.append(
            {
                "task_id": task_id,
                "domain": "hr",
                "domain_index": index,
                "task_request": _task_request(row),
                "available_tools": _tool_signatures(info.get("zapier_tools", [])),
                "initial_state": info.get("initial_state", {}),
                "split_hash": hashlib.sha256(
                    (SPLIT_SALT + task_id).encode()
                ).hexdigest(),
            }
        )
    return sorted(selected, key=lambda task: task["split_hash"])


def build_family_manifest() -> dict[str, Any]:
    """Select the frozen family and apply its deterministic 12/5/8 split."""
    tasks = _family_rows()
    expected = sum(SPLIT_SIZES.values())
    if len(tasks) != expected:
        raise RuntimeError(
            f"Family predicate selected {len(tasks)} tasks; expected {expected}"
        )
    train_end = SPLIT_SIZES["train"]
    validation_end = train_end + SPLIT_SIZES["validation"]
    raw_splits = {
        "train": tasks[:train_end],
        "validation": tasks[train_end:validation_end],
        "test": tasks[validation_end:],
    }
    splits = {
        name: [
            build_task_card(task) | {"split_hash": task["split_hash"]} for task in rows
        ]
        for name, rows in raw_splits.items()
    }
    return {
        "schema_version": 1,
        "family_id": FAMILY_ID,
        "benchmark": "AutomationBench-public",
        "family_predicate": {
            "domain": "hr",
            "exact_zapier_tools": list(FAMILY_TOOLS),
            "uses": ["public task prompt", "available tool signature"],
            "excludes": ["assertions", "trajectories", "scores"],
        },
        "split_rule": {
            "algorithm": "sha256-lexicographic",
            "salt": SPLIT_SALT,
            "sizes": dict(SPLIT_SIZES),
        },
        "counts": dict(SPLIT_SIZES) | {"total": expected},
        "splits": splits,
    }


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    temporary.replace(path)


def artifact_sha256(artifact: Any) -> str:
    return hashlib.sha256(
        json.dumps(artifact, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(
        (
            item
            for item in root.rglob("*")
            if item.is_file()
            and "__pycache__" not in item.parts
            and ".venv" not in item.parts
            and ".git" not in item.parts
            and item.suffix.lower() in {".py", ".toml", ".lock", ".jsonc"}
        ),
        key=lambda item: item.relative_to(root).as_posix(),
    ):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def write_family_manifest(path: Path) -> dict[str, Any]:
    payload = build_family_manifest()
    encoded = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if existing != encoded:
            raise RuntimeError(
                f"Frozen manifest differs from current selection: {path}"
            )
        return payload
    atomic_write(path, encoded)
    return payload


def _mutation_diff(before: Any, after: Any, path: str = "$") -> list[dict[str, Any]]:
    """Describe observable state changes without consulting evaluator assertions."""
    if isinstance(before, dict) and isinstance(after, dict):
        changes: list[dict[str, Any]] = []
        for key in sorted(set(before) | set(after)):
            child = f"{path}.{key}"
            if key not in before:
                changes.append(
                    {"path": child, "before": None, "after": copy.deepcopy(after[key])}
                )
            elif key not in after:
                changes.append(
                    {"path": child, "before": copy.deepcopy(before[key]), "after": None}
                )
            else:
                changes.extend(_mutation_diff(before[key], after[key], child))
        return changes
    if isinstance(before, list) and isinstance(after, list):
        changes = []
        for index in range(max(len(before), len(after))):
            child = f"{path}[{index}]"
            if index >= len(before):
                changes.append(
                    {
                        "path": child,
                        "before": None,
                        "after": copy.deepcopy(after[index]),
                    }
                )
            elif index >= len(after):
                changes.append(
                    {
                        "path": child,
                        "before": copy.deepcopy(before[index]),
                        "after": None,
                    }
                )
            else:
                changes.extend(_mutation_diff(before[index], after[index], child))
        return changes
    if before == after:
        return []
    return [
        {"path": path, "before": copy.deepcopy(before), "after": copy.deepcopy(after)}
    ]


def build_optimizer_view(
    evaluation: Mapping[str, Any], *, initial_state: Mapping[str, Any]
) -> dict[str, Any]:
    """Build the only evaluator result view that Analyzer is allowed to read.

    This deliberately copies a small allowlist rather than attempting to redact an
    evaluator payload.  New assertion fields therefore remain sealed by default.
    """
    cost_keys = (
        "steps",
        "tool_calls",
        "student_tokens",
        "input_tokens",
        "output_tokens",
        "runtime_seconds",
    )
    end_state = evaluation.get("end_state", initial_state)
    trajectory = copy.deepcopy(evaluation.get("messages", []))
    final_answer = evaluation.get("final_answer")
    if final_answer is None:
        for message in reversed(trajectory):
            if isinstance(message, Mapping) and message.get("role") == "assistant":
                content = message.get("content")
                if content:
                    final_answer = content
                    break
    return {
        "schema_version": 1,
        "task_id": str(evaluation.get("name") or evaluation.get("task_id") or ""),
        "score": float(evaluation.get("score", 0.0)),
        "trajectory": trajectory,
        "tool_results": copy.deepcopy(evaluation.get("tool_results", [])),
        "mutation_diff": _mutation_diff(initial_state, end_state),
        "final_answer": copy.deepcopy(final_answer),
        "skillgraph_trace": copy.deepcopy(evaluation.get("skillgraph_trace")),
        "run_fingerprint": copy.deepcopy(evaluation.get("run_fingerprint")),
        "runner_failure": bool(evaluation.get("errors")),
        "cost": {key: evaluation[key] for key in cost_keys if key in evaluation},
    }


def _task_means(scores: Mapping[str, Sequence[float]]) -> dict[str, float]:
    means: dict[str, float] = {}
    for task_id, observations in scores.items():
        if not observations:
            raise ValueError(f"Task {task_id!r} has no valid observations")
        means[str(task_id)] = statistics.fmean(float(value) for value in observations)
    return means


def validation_gate(
    current: Mapping[str, Sequence[float]],
    candidate: Mapping[str, Sequence[float]],
    *,
    artifact_valid: bool,
) -> dict[str, Any]:
    """Apply the pre-registered validation acceptance rule at task level."""
    if set(current) != set(candidate):
        raise ValueError("Current and candidate validation task sets differ")
    current_means = _task_means(current)
    candidate_means = _task_means(candidate)
    deltas = {
        task: candidate_means[task] - current_means[task] for task in current_means
    }
    mean_delta = statistics.fmean(deltas.values())
    wins = sum(delta > 1e-12 for delta in deltas.values())
    losses = sum(delta < -1e-12 for delta in deltas.values())
    worst_delta = min(deltas.values())
    reasons: list[str] = []
    if not artifact_valid:
        reasons.append("artifact_invalid")
    if mean_delta + 1e-12 < 0.05:
        reasons.append("insufficient_mean_delta")
    if wins <= losses:
        reasons.append("wins_not_greater_than_losses")
    if worst_delta < -0.10 - 1e-12:
        reasons.append("large_task_regression")
    return {
        "decision": "ACCEPT" if not reasons else "REJECT",
        "reasons": reasons,
        "mean_delta": mean_delta,
        "wins": wins,
        "ties": len(deltas) - wins - losses,
        "losses": losses,
        "worst_task_delta": worst_delta,
        "task_deltas": deltas,
    }


@dataclass
class ExperimentState:
    """Durable state machine protecting the single sealed test opening."""

    path: Path
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(cls, path: Path) -> "ExperimentState":
        if path.exists():
            raise FileExistsError(path)
        state = cls(
            path=path,
            payload={
                "schema_version": 1,
                "phase": "authoring",
                "authoring_stage": "empty",
                "artifact_hashes": {},
            },
        )
        state._save()
        return state

    @classmethod
    def load(cls, path: Path) -> "ExperimentState":
        return cls(path=path, payload=json.loads(path.read_text(encoding="utf-8")))

    def _save(self) -> None:
        atomic_write(
            self.path, json.dumps(self.payload, ensure_ascii=False, indent=2) + "\n"
        )

    def freeze_artifacts(self, artifacts: Mapping[str, Any]) -> None:
        if self.payload["phase"] != "authoring":
            raise RuntimeError("Artifacts can only be frozen after authoring")
        hashes = {}
        for name, artifact in sorted(artifacts.items()):
            hashes[str(name)] = artifact_sha256(artifact)
        if not hashes:
            raise ValueError("At least one artifact must be frozen")
        self.payload.update(phase="artifacts_frozen", artifact_hashes=hashes)
        self._save()

    def open_test(self) -> None:
        phase = self.payload["phase"]
        if phase == "authoring":
            raise RuntimeError("Sealed test cannot open until artifacts are frozen")
        if phase != "artifacts_frozen":
            raise RuntimeError("Sealed test has already opened")
        self.payload["phase"] = "test_open"
        self._save()

    def complete_test(self) -> None:
        if self.payload["phase"] != "test_open":
            raise RuntimeError("Sealed test is not open")
        self.payload["phase"] = "complete"
        self._save()


def _percentile(sorted_values: Sequence[float], probability: float) -> float:
    if not sorted_values:
        raise ValueError("Cannot take percentile of an empty sequence")
    position = probability * (len(sorted_values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = position - lower
    return sorted_values[lower] * (1 - fraction) + sorted_values[upper] * fraction


def primary_comparison(
    incremental_graph: Mapping[str, Sequence[float]],
    per_task_static_markdown: Mapping[str, Sequence[float]],
    *,
    samples: int = 10_000,
    seed: int = 1,
) -> dict[str, Any]:
    """Paired task-level bootstrap for the pre-registered primary comparison."""
    if set(incremental_graph) != set(per_task_static_markdown):
        raise ValueError("Primary arms do not contain the same test tasks")
    graph_means = _task_means(incremental_graph)
    markdown_means = _task_means(per_task_static_markdown)
    task_ids = sorted(graph_means)
    if not task_ids:
        raise ValueError("Primary comparison has no tasks")
    deltas = {task: graph_means[task] - markdown_means[task] for task in task_ids}
    mean_delta = statistics.fmean(deltas.values())
    rng = random.Random(seed)
    bootstrap = sorted(
        statistics.fmean(deltas[rng.choice(task_ids)] for _ in task_ids)
        for _ in range(samples)
    )
    lower = _percentile(bootstrap, 0.025)
    upper = _percentile(bootstrap, 0.975)
    if mean_delta > 0 and lower > 0:
        conclusion = "incremental_graph_wins"
    elif mean_delta < 0 and upper < 0:
        conclusion = "incremental_graph_loses"
    elif mean_delta > 0:
        conclusion = "directional_incremental_graph_advantage"
    elif mean_delta < 0:
        conclusion = "directional_per_task_markdown_advantage"
    else:
        conclusion = "no_difference"
    wins = sum(delta > 1e-12 for delta in deltas.values())
    losses = sum(delta < -1e-12 for delta in deltas.values())
    return {
        "tasks": len(task_ids),
        "mean_delta": mean_delta,
        "ci95": [lower, upper],
        "conclusion": conclusion,
        "task_win_tie_loss": {
            "wins": wins,
            "ties": len(task_ids) - wins - losses,
            "losses": losses,
        },
        "task_deltas": deltas,
        "bootstrap_samples": samples,
        "bootstrap_seed": seed,
    }


MINIMAL_MARKDOWN = """# HR policy-governed batch processing

1. Inspect the task request, available operations, relevant records, and policy evidence.
2. Act only on effects supported by the observed evidence and policy.
3. Verify every requested effect and material negative constraint before reporting.

If required evidence is unavailable, report the blocker instead of guessing.
"""


@dataclass(frozen=True)
class FamilyPaths:
    run_dir: Path

    @property
    def manifest(self) -> Path:
        return self.run_dir / "manifest.json"

    @property
    def state(self) -> Path:
        return self.run_dir / "experiment-state.json"

    @property
    def artifacts(self) -> Path:
        return self.run_dir / "artifacts"

    @property
    def records(self) -> Path:
        return self.run_dir / "records"

    @property
    def evaluations(self) -> Path:
        return self.run_dir / "evaluations"

    @property
    def report(self) -> Path:
        return self.run_dir / "report.json"


class Author(Protocol):
    def generate(self, prompt: str) -> Any: ...


class Evaluator(Protocol):
    def evaluate(
        self,
        task_ids: Sequence[str],
        artifact: str | Mapping[str, Any] | None,
        *,
        graph: bool,
        repetitions: int,
        label: str,
    ) -> dict[str, list[dict[str, Any]]]: ...


class DeepSeekAuthor:
    """Pi-backed author fixed to the pre-registered artifact model."""

    def __init__(self, *, timeout_seconds: int = 600) -> None:
        self.timeout_seconds = timeout_seconds

    def generate(self, prompt: str) -> dict[str, Any]:
        from automationbench_pipeline import invoke_pi_generator

        api_key = os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_BASE_URL")
        if not api_key or not base_url:
            raise RuntimeError("OPENAI_API_KEY and OPENAI_BASE_URL are required")
        request = {
            "version": 1,
            "prompt": prompt,
            "cwd": str(ROOT.resolve()),
            "model": {"id": AUTHOR_MODEL, "baseUrl": base_url},
        }
        response, stderr = invoke_pi_generator(
            request, timeout_seconds=self.timeout_seconds
        )
        if response.get("error"):
            raise RuntimeError(f"Artifact author failed: {response['error']}")
        response["stderr_tail"] = stderr[-1000:]
        response["model"] = AUTHOR_MODEL
        return response


def _author_text(author: Author, prompt: str) -> tuple[str, dict[str, Any]]:
    raw = author.generate(prompt)
    if isinstance(raw, str):
        return raw.strip(), {"model": "test-double"}
    if not isinstance(raw, Mapping):
        raise TypeError("Author response must be text or a mapping")
    text_value = raw.get("skillMd") or raw.get("text")
    if not isinstance(text_value, str) or not text_value.strip():
        raise ValueError("Author response contains no text")
    record = {
        key: copy.deepcopy(raw.get(key))
        for key in ("model", "tokenCounts", "usage", "cost", "attempts")
        if key in raw
    }
    return text_value.strip(), record


def _extract_json(text_value: str) -> Any:
    stripped = text_value.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", stripped, re.S | re.I)
    if fence:
        stripped = fence.group(1).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start_candidates = [
            position
            for position in (stripped.find("{"), stripped.find("["))
            if position >= 0
        ]
        if not start_candidates:
            raise
        start = min(start_candidates)
        decoder = json.JSONDecoder()
        return decoder.raw_decode(stripped[start:])[0]


def validate_markdown_artifact(markdown: str) -> dict[str, int]:
    if not markdown.strip():
        raise ValueError("Markdown artifact is empty")
    if len(markdown) > 40_000:
        raise ValueError("Markdown artifact is too large")
    forbidden = (
        "assertion_results",
        "expected answer",
        "gold answer",
        "evaluator assertion",
    )
    lower = markdown.lower()
    if any(term in lower for term in forbidden):
        raise ValueError("Markdown artifact contains evaluator-only vocabulary")
    return {"characters": len(markdown), "lines": len(markdown.splitlines())}


def apply_markdown_edit(
    markdown: str, edit: Mapping[str, Any]
) -> tuple[str, dict[str, Any]]:
    """Apply one exact local replacement/insert; whole-document rewrites are rejected."""
    operator = str(edit.get("operator") or "")
    if operator == "NO_EDIT":
        return markdown, {"operator": operator, "changed": False}
    allowed = {
        "UPDATE_INSTRUCTION",
        "INSERT_STEP",
        "DELETE_STEP",
        "ADD_CONDITION",
        "ADD_VERIFICATION",
        "ADD_RECOVERY",
    }
    if operator not in allowed:
        raise ValueError(f"Unsupported Markdown edit operator {operator!r}")
    old = str(edit.get("old_text") or "")
    new = str(edit.get("new_text") or "")
    if not old or markdown.count(old) != 1:
        raise ValueError("Markdown edit old_text must match exactly once")
    if operator != "DELETE_STEP" and not new.strip():
        raise ValueError("Markdown edit new_text cannot be empty")
    if len(old) > max(800, int(len(markdown) * 0.35)):
        raise ValueError("Markdown edit is not local")
    candidate = markdown.replace(old, new, 1)
    validate_markdown_artifact(candidate)
    return candidate, {
        "operator": operator,
        "changed": candidate != markdown,
        "before_sha256": hashlib.sha256(markdown.encode()).hexdigest(),
        "after_sha256": hashlib.sha256(candidate.encode()).hexdigest(),
    }


def _artifact_prompt(role: str, payload: Mapping[str, Any]) -> str:
    contracts = {
        "family-static-markdown": (
            "Write one concise shared Markdown operating skill for all task cards. "
            "Return Markdown only. Do not invent instance values or evaluator criteria."
        ),
        "one-shot-family-skillgraph": (
            "Author one complete executable SkillGraph JSON object for all task cards. "
            "Use only the supported node/edit semantics and return JSON only."
        ),
        "analyzer": (
            "Analyze the supplied assertion-free rollout evidence. Return JSON with decision "
            "NO_EDIT or EDIT, diagnosis, evidence, and confidence. Treat runner failures and "
            "isolated stochastic failures as NO_EDIT."
        ),
        "graph-curator": (
            "Propose at most one atomic semantic SkillGraph edit. Return one JSON edit object "
            f"whose operator is in {sorted(SUPPORTED_EDIT_OPERATORS)}. Never rewrite the graph."
        ),
        "markdown-curator": (
            "Propose at most one local Markdown edit. Return JSON with operator, old_text, and "
            "new_text. Never rewrite the whole artifact."
        ),
        "batch-refine-skillgraph": (
            "Using exactly the supplied training evidence, write a complete refined SkillGraph "
            "JSON object starting conceptually from G0. Return JSON only."
        ),
        "per-task-static-markdown": (
            "Write a Markdown operating skill for this task in one pass. You may use the public "
            "prompt, tool signatures, and full initial state. Do not infer assertions or expected "
            "answers. Return Markdown only."
        ),
    }
    return (
        "You are an artifact author in a sealed AutomationBench experiment.\n"
        + contracts[role]
        + "\nWrap the requested Markdown or JSON payload in <skill_md> and </skill_md> markers; "
        "emit nothing outside those markers."
        + "\n\nINPUT (JSON):\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def _task_lookup() -> dict[str, dict[str, Any]]:
    return {task["task_id"]: task for task in _family_rows()}


def _batch_ids(manifest: Mapping[str, Any]) -> list[list[str]]:
    train = [task["task_id"] for task in manifest["splits"]["train"]]
    batches, offset = [], 0
    for size in TRAIN_BATCH_SIZES:
        batches.append(train[offset : offset + size])
        offset += size
    return batches


def _score_map(
    results: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, list[float]]:
    return {
        task_id: [float(observation.get("score", 0.0)) for observation in observations]
        for task_id, observations in results.items()
        if observations
    }


def _numeric_totals(value: Any) -> dict[str, float]:
    totals: dict[str, float] = {}
    if isinstance(value, Mapping):
        for key, child in value.items():
            metric_key = str(key).lower()
            if isinstance(child, (int, float)) and any(
                marker in metric_key
                for marker in ("token", "cost", "tool_call", "steps", "runtime_seconds")
            ):
                totals[str(key)] = totals.get(str(key), 0.0) + float(child)
            else:
                for nested_key, amount in _numeric_totals(child).items():
                    totals[nested_key] = totals.get(nested_key, 0.0) + amount
    elif isinstance(value, list):
        for child in value:
            for nested_key, amount in _numeric_totals(child).items():
                totals[nested_key] = totals.get(nested_key, 0.0) + amount
    return totals


def _merge_totals(*parts: Mapping[str, float]) -> dict[str, float]:
    merged: dict[str, float] = {}
    for part in parts:
        for key, amount in part.items():
            merged[key] = merged.get(key, 0.0) + float(amount)
    return merged


def _paired_validation(
    evaluator: Evaluator,
    task_ids: Sequence[str],
    current: str | Mapping[str, Any],
    candidate: str | Mapping[str, Any],
    *,
    graph: bool,
    round_index: int,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    current_results = {task_id: [] for task_id in task_ids}
    candidate_results = {task_id: [] for task_id in task_ids}
    rng = random.Random(17_000 + round_index)
    for task_id in task_ids:
        for repetition in range(3):
            order = ["current", "candidate"]
            rng.shuffle(order)
            for arm in order:
                artifact = current if arm == "current" else candidate
                result = evaluator.evaluate(
                    [task_id],
                    artifact,
                    graph=graph,
                    repetitions=1,
                    label=f"validation-r{round_index}-{task_id}-{repetition}-{arm}",
                )
                target = current_results if arm == "current" else candidate_results
                target[task_id].extend(result.get(task_id, []))
    return current_results, candidate_results


def optimize_artifact(
    *,
    kind: str,
    initial: str | Mapping[str, Any],
    manifest: Mapping[str, Any],
    author: Author,
    evaluator: Evaluator,
    records_dir: Path,
) -> tuple[str | dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Run the five frozen train batches and paired validation gates."""
    if kind not in {"graph", "markdown"}:
        raise ValueError("kind must be graph or markdown")
    current: str | dict[str, Any] = copy.deepcopy(initial)  # type: ignore[assignment]
    validation_ids = [task["task_id"] for task in manifest["splits"]["validation"]]
    task_lookup = _task_lookup()
    cards = {
        task["task_id"]: task
        for split in ("train", "validation")
        for task in manifest["splits"][split]
    }
    history: list[dict[str, Any]] = []
    all_views: list[dict[str, Any]] = []
    for round_index, task_ids in enumerate(_batch_ids(manifest), start=1):
        train_results = evaluator.evaluate(
            task_ids,
            current,
            graph=kind == "graph",
            repetitions=3,
            label=f"{kind}-train-r{round_index}",
        )
        missing = {
            task_id: 3 - len(train_results.get(task_id, []))
            for task_id in task_ids
            if len(train_results.get(task_id, [])) < 3
        }
        if missing:
            record = {
                "round": round_index,
                "diagnosis": {"decision": "NO_EDIT", "reason": "missing_observations"},
                "candidate_diff": {"operator": "NO_EDIT", "changed": False},
                "gate": "NO_EDIT",
                "missing_observations": missing,
            }
            history.append(record)
            atomic_write(
                records_dir / f"{kind}-round-{round_index}.json",
                json.dumps(record, ensure_ascii=False, indent=2) + "\n",
            )
            continue
        views = [
            build_optimizer_view(
                observation,
                initial_state=task_lookup[task_id]["initial_state"],
            )
            | {"task_card": copy.deepcopy(cards[task_id])}
            for task_id, observations in train_results.items()
            for observation in observations
        ]
        all_views.extend(views)
        train_rollout_totals = _numeric_totals(views)
        analyzer_text, analyzer_usage = _author_text(
            author,
            _artifact_prompt(
                "analyzer",
                {"kind": kind, "artifact": current, "rollouts": views},
            ),
        )
        diagnosis = _extract_json(analyzer_text)
        if diagnosis.get("decision") == "NO_EDIT":
            record = {
                "round": round_index,
                "diagnosis": diagnosis,
                "candidate_diff": {"operator": "NO_EDIT", "changed": False},
                "gate": "NO_EDIT",
                "author_usage": analyzer_usage,
                "train_rollout_totals": train_rollout_totals,
            }
            history.append(record)
            atomic_write(
                records_dir / f"{kind}-round-{round_index}.json",
                json.dumps(record, ensure_ascii=False, indent=2) + "\n",
            )
            continue
        curator_role = "graph-curator" if kind == "graph" else "markdown-curator"
        edit_text, curator_usage = _author_text(
            author,
            _artifact_prompt(
                curator_role, {"artifact": current, "diagnosis": diagnosis}
            ),
        )
        edit = _extract_json(edit_text)
        try:
            if kind == "graph":
                candidate, diff = apply_atomic_edit(current, edit)  # type: ignore[arg-type]
                artifact_valid = bool(validate_graph(candidate))
            else:
                candidate, diff = apply_markdown_edit(str(current), edit)
                artifact_valid = bool(validate_markdown_artifact(candidate))
        except (KeyError, TypeError, ValueError) as exc:
            record = {
                "round": round_index,
                "diagnosis": diagnosis,
                "candidate_diff": {"operator": edit.get("operator"), "error": str(exc)},
                "proposed_edit": edit,
                "gate": "REJECT",
                "author_usage": {"analyzer": analyzer_usage, "curator": curator_usage},
                "train_rollout_totals": train_rollout_totals,
            }
            history.append(record)
            atomic_write(
                records_dir / f"{kind}-round-{round_index}.json",
                json.dumps(record, ensure_ascii=False, indent=2) + "\n",
            )
            continue
        candidate_suffix = ".json" if kind == "graph" else ".md"
        candidate_text = (
            json.dumps(candidate, ensure_ascii=False, indent=2) + "\n"
            if kind == "graph"
            else str(candidate).rstrip() + "\n"
        )
        atomic_write(
            records_dir / "candidates" / f"round-{round_index}{candidate_suffix}",
            candidate_text,
        )
        current_eval, candidate_eval = _paired_validation(
            evaluator,
            validation_ids,
            current,
            candidate,
            graph=kind == "graph",
            round_index=round_index,
        )
        validation_missing = {
            f"{side}:{task_id}": 3 - len(results.get(task_id, []))
            for side, results in (
                ("current", current_eval),
                ("candidate", candidate_eval),
            )
            for task_id in validation_ids
            if len(results.get(task_id, [])) < 3
        }
        if validation_missing:
            gate = {
                "decision": "REJECT",
                "reasons": ["missing_validation_observations"],
                "missing_observations": validation_missing,
            }
        else:
            gate = validation_gate(
                _score_map(current_eval),
                _score_map(candidate_eval),
                artifact_valid=artifact_valid,
            )
        record = {
            "round": round_index,
            "diagnosis": diagnosis,
            "proposed_edit": edit,
            "candidate_diff": diff,
            "current_artifact_sha256": artifact_sha256(current),
            "candidate_artifact_sha256": artifact_sha256(candidate),
            "gate": gate,
            "author_usage": {"analyzer": analyzer_usage, "curator": curator_usage},
            "train_rollout_totals": train_rollout_totals,
            "validation_rollout_totals": _numeric_totals(
                [current_eval, candidate_eval]
            ),
        }
        history.append(record)
        atomic_write(
            records_dir / f"{kind}-round-{round_index}.json",
            json.dumps(record, ensure_ascii=False, indent=2) + "\n",
        )
        if gate["decision"] == "ACCEPT":
            current = candidate
    return current, history, all_views


class AutomationBenchEvaluator:
    """Reset-per-rollout subprocess adapter with bounded infrastructure retries."""

    def __init__(
        self, output_dir: Path, *, max_steps: int = 20, student_model: str | None = None
    ) -> None:
        self.output_dir = output_dir
        self.max_steps = max_steps
        if self.max_steps != 20:
            raise ValueError(
                "The registered experiment requires exactly 20 student steps"
            )
        self.runtime_sha256 = tree_sha256(AUTOMATIONBENCH_ROOT)
        self.student_model = (
            student_model or os.getenv("STUDENT_MODEL_ID") or os.getenv("MODEL_ID")
        )
        if not self.student_model:
            raise RuntimeError("STUDENT_MODEL_ID or MODEL_ID is required")

    def evaluate(
        self,
        task_ids: Sequence[str],
        artifact: str | Mapping[str, Any] | None,
        *,
        graph: bool,
        repetitions: int,
        label: str,
    ) -> dict[str, list[dict[str, Any]]]:
        base_url = os.getenv("OPENAI_BASE_URL")
        if not base_url or not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_BASE_URL and OPENAI_API_KEY are required")
        results = {task_id: [] for task_id in task_ids}
        for task_id in task_ids:
            for repetition in range(repetitions):
                stem = re.sub(
                    r"[^a-zA-Z0-9_.-]", "-", f"{label}-{task_id}-{repetition}"
                )
                selection = self.output_dir / "selected" / f"{stem}.json"
                injection = self.output_dir / "injections" / f"{stem}.json"
                fingerprint = {
                    "student_model": self.student_model,
                    "max_steps": self.max_steps,
                    "toolset": "limited_zapier",
                    "business_tools": list(FAMILY_TOOLS),
                    "base_url": base_url,
                    "api": "chat_completions",
                    "artifact_sha256": artifact_sha256(artifact)
                    if artifact is not None
                    else None,
                    "runtime_sha256": self.runtime_sha256,
                }
                if selection.is_file():
                    selected = json.loads(selection.read_text(encoding="utf-8"))
                    if selected.get("config") != fingerprint:
                        raise RuntimeError(f"Immutable rollout collision: {selection}")
                    results[task_id].append(selected["result"])
                    continue
                if artifact is not None:
                    mapping = {task_id: copy.deepcopy(artifact)}
                    encoded = json.dumps(mapping, ensure_ascii=False, indent=2) + "\n"
                    if (
                        injection.exists()
                        and injection.read_text(encoding="utf-8") != encoded
                    ):
                        raise RuntimeError(
                            f"Immutable injection collision: {injection}"
                        )
                    if not injection.exists():
                        atomic_write(injection, encoded)
                last_error = ""
                for attempt in range(3):
                    output = (
                        self.output_dir
                        / "attempts"
                        / f"{stem}-attempt-{attempt + 1}.json"
                    )
                    failure = output.with_suffix(".failure.json")
                    if failure.exists():
                        last_error = "runner attempt previously failed"
                        continue
                    if not output.exists():
                        command = [
                            str(
                                AUTOMATIONBENCH_ROOT
                                / ".venv"
                                / "Scripts"
                                / "python.exe"
                            ),
                            "-m",
                            "automationbench.scripts.eval",
                            "--model",
                            self.student_model,
                            "--base-url",
                            base_url,
                            "--api-key-var",
                            "OPENAI_API_KEY",
                            "--api",
                            "chat_completions",
                            "--domains",
                            "hr",
                            "--tasks",
                            task_id,
                            "--toolset",
                            "limited_zapier",
                            "--max-steps",
                            str(self.max_steps),
                            "--max-concurrent",
                            "1",
                            "--no-ensure-complete",
                            "--export-json",
                            str(output),
                        ]
                        if artifact is not None:
                            command.extend(
                                [
                                    "--task-skillgraphs-json"
                                    if graph
                                    else "--task-instructions-json",
                                    str(injection),
                                ]
                            )
                        output.parent.mkdir(parents=True, exist_ok=True)
                        completed = subprocess.run(command, cwd=AUTOMATIONBENCH_ROOT)
                        if completed.returncode:
                            atomic_write(
                                failure,
                                json.dumps(
                                    {
                                        "attempt": attempt + 1,
                                        "exit_code": completed.returncode,
                                        "export_path": str(output.resolve())
                                        if output.exists()
                                        else None,
                                    },
                                    indent=2,
                                )
                                + "\n",
                            )
                            last_error = f"runner exit code {completed.returncode}"
                            continue
                    if not output.is_file():
                        last_error = "runner produced no export"
                        continue
                    try:
                        payload = json.loads(output.read_text(encoding="utf-8"))
                    except json.JSONDecodeError:
                        last_error = "evaluation output was not valid JSON"
                        continue
                    tasks = payload.get("tasks", [])
                    if len(tasks) != 1:
                        last_error = (
                            "evaluation output did not contain exactly one task"
                        )
                        continue
                    trace = tasks[0].get("skillgraph_trace", {})
                    post_terminal_violation = trace.get("post_terminal_violation")
                    if tasks[0].get("errors") and not post_terminal_violation:
                        last_error = "runner result contained errors"
                        continue
                    result = tasks[0]
                    if graph and (
                        trace.get("terminal_status")
                        not in {"finish", "fail", "blocked"}
                        or post_terminal_violation
                    ):
                        result["score"] = 0.0
                        result["passed"] = False
                        result["graph_runtime_failure"] = (
                            f"post_terminal_tool:{post_terminal_violation}"
                            if post_terminal_violation
                            else "non_terminal_final_answer"
                        )
                    result["run_fingerprint"] = {
                        "config": fingerprint,
                        "attempt": attempt + 1,
                    }
                    atomic_write(
                        selection,
                        json.dumps(
                            {
                                "config": fingerprint,
                                "result_path": str(output.resolve()),
                                "attempt": attempt + 1,
                                "result": result,
                            },
                            ensure_ascii=False,
                            indent=2,
                        )
                        + "\n",
                    )
                    results[task_id].append(result)
                    break
                else:
                    atomic_write(
                        self.output_dir / "missing" / f"{stem}.json",
                        json.dumps({"task_id": task_id, "reason": last_error}, indent=2)
                        + "\n",
                    )
        return results


class FamilyExperiment:
    def __init__(
        self, paths: FamilyPaths, author: Author, evaluator: Evaluator
    ) -> None:
        self.paths = paths
        self.author = author
        self.evaluator = evaluator

    def _configuration(self) -> dict[str, Any]:
        manifest_bytes = self.paths.manifest.read_bytes()
        student_model = str(getattr(self.evaluator, "student_model", "test-double"))
        max_steps = int(getattr(self.evaluator, "max_steps", 20))
        runtime_sha = getattr(self.evaluator, "runtime_sha256", None) or tree_sha256(
            AUTOMATIONBENCH_ROOT
        )
        config = {
            "schema_version": 1,
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "student_model": student_model,
            "author_model": AUTHOR_MODEL,
            "max_steps": max_steps,
            "toolset": "limited_zapier",
            "business_tools": list(FAMILY_TOOLS),
            "tool_signatures_sha256": artifact_sha256(_tool_signatures(FAMILY_TOOLS)),
            "base_url": os.getenv("OPENAI_BASE_URL")
            if student_model != "test-double"
            else None,
            "api": "chat_completions",
            "runtime_sha256": str(runtime_sha),
            "orchestrator_sha256": hashlib.sha256(
                Path(__file__).read_bytes()
            ).hexdigest(),
        }
        config["fingerprint"] = artifact_sha256(config)
        return config

    def _bind_or_verify_configuration(self, state: ExperimentState) -> None:
        current = self._configuration()
        frozen = state.payload.get("experiment_config")
        if frozen is not None and frozen != current:
            raise RuntimeError(
                "Experimental configuration differs from the frozen config"
            )
        if frozen is None:
            if state.payload["phase"] != "authoring":
                raise RuntimeError("Frozen experiment is missing its configuration")
            state.payload["experiment_config"] = current
            state._save()

    def _manifest(self) -> dict[str, Any]:
        return json.loads(self.paths.manifest.read_text(encoding="utf-8"))

    def _write_artifact(self, name: str, artifact: Any) -> None:
        suffix = ".json" if isinstance(artifact, Mapping) else ".md"
        text_value = (
            json.dumps(artifact, ensure_ascii=False, indent=2) + "\n"
            if isinstance(artifact, Mapping)
            else str(artifact).rstrip() + "\n"
        )
        atomic_write(self.paths.artifacts / f"{name}{suffix}", text_value)

    def _read_artifact(self, name: str, *, graph: bool) -> Any:
        path = self.paths.artifacts / f"{name}{'.json' if graph else '.md'}"
        text_value = path.read_text(encoding="utf-8")
        return json.loads(text_value) if graph else text_value

    def author_initial(self) -> dict[str, Any]:
        manifest = self._manifest()
        if self.paths.state.exists():
            state = ExperimentState.load(self.paths.state)
            if state.payload["phase"] != "authoring":
                raise RuntimeError("Initial artifacts cannot be authored after freeze")
            if state.payload.get("authoring_stage", "empty") != "empty":
                raise RuntimeError("Initial artifacts have already been authored")
        else:
            state = ExperimentState.create(self.paths.state)
        self._bind_or_verify_configuration(state)
        cards = manifest["splits"]["train"]
        markdown_prompt = _artifact_prompt(
            "family-static-markdown", {"task_cards": cards}
        )
        markdown, markdown_usage = _author_text(
            self.author,
            markdown_prompt,
        )
        validate_markdown_artifact(markdown)
        graph_prompt = _artifact_prompt(
            "one-shot-family-skillgraph",
            {"task_cards": cards, "schema_example": minimal_graph()},
        )
        graph_text, graph_usage = _author_text(
            self.author,
            graph_prompt,
        )
        graph = _extract_json(graph_text)
        validate_graph(graph)
        artifacts = {
            "family-static-markdown": markdown,
            "family-incremental-markdown": MINIMAL_MARKDOWN,
            "one-shot-family-skillgraph": graph,
            "incremental-skillgraph": minimal_graph(),
        }
        for name, artifact in artifacts.items():
            self._write_artifact(name, artifact)
        record = {
            "model": AUTHOR_MODEL,
            "family_static_prompt_sha256": hashlib.sha256(
                markdown_prompt.encode()
            ).hexdigest(),
            "family_static_artifact_sha256": artifact_sha256(markdown),
            "family_static_usage": markdown_usage,
            "one_shot_graph_prompt_sha256": hashlib.sha256(
                graph_prompt.encode()
            ).hexdigest(),
            "one_shot_graph_artifact_sha256": artifact_sha256(graph),
            "one_shot_graph_usage": graph_usage,
        }
        atomic_write(
            self.paths.records / "initial-authoring.json",
            json.dumps(record, ensure_ascii=False, indent=2) + "\n",
        )
        state.payload["authoring_stage"] = "initial_authored"
        state._save()
        return artifacts

    def optimize(self) -> dict[str, Any]:
        state = ExperimentState.load(self.paths.state)
        if state.payload["phase"] != "authoring":
            raise RuntimeError("Optimization is only allowed during authoring")
        if state.payload.get("authoring_stage") != "initial_authored":
            raise RuntimeError(
                "Optimization requires freshly authored initial artifacts"
            )
        self._bind_or_verify_configuration(state)
        optimization_run_id = state.payload["experiment_config"]["fingerprint"][:16]
        state.payload["authoring_stage"] = "optimizing"
        state.payload["optimization_run_id"] = optimization_run_id
        state._save()
        manifest = self._manifest()
        incremental_graph, graph_history, graph_views = optimize_artifact(
            kind="graph",
            initial=self._read_artifact("incremental-skillgraph", graph=True),
            manifest=manifest,
            author=self.author,
            evaluator=self.evaluator,
            records_dir=self.paths.records / "incremental-graph" / optimization_run_id,
        )
        incremental_markdown, markdown_history, _ = optimize_artifact(
            kind="markdown",
            initial=self._read_artifact("family-incremental-markdown", graph=False),
            manifest=manifest,
            author=self.author,
            evaluator=self.evaluator,
            records_dir=self.paths.records
            / "incremental-markdown"
            / optimization_run_id,
        )
        batch_text, batch_usage = _author_text(
            self.author,
            _artifact_prompt(
                "batch-refine-skillgraph",
                {"initial_graph": minimal_graph(), "training_evidence": graph_views},
            ),
        )
        batch_graph = _extract_json(batch_text)
        validate_graph(batch_graph)
        self._write_artifact("incremental-skillgraph", incremental_graph)
        self._write_artifact("family-incremental-markdown", incremental_markdown)
        self._write_artifact("batch-refine-skillgraph", batch_graph)
        summary = {
            "incremental_graph_rounds": graph_history,
            "incremental_markdown_rounds": markdown_history,
            "batch_refine_usage": batch_usage,
            "training_evidence_sha256": hashlib.sha256(
                json.dumps(graph_views, ensure_ascii=False, sort_keys=True).encode()
            ).hexdigest(),
        }
        atomic_write(
            self.paths.records / "optimization-summary.json",
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        )
        state.payload["authoring_stage"] = "optimized"
        state._save()
        return summary

    def freeze(self) -> dict[str, str]:
        artifacts = self._family_artifacts()
        state = ExperimentState.load(self.paths.state)
        if state.payload.get("authoring_stage") != "optimized":
            raise RuntimeError("Freeze requires completed optimization")
        self._bind_or_verify_configuration(state)
        state.freeze_artifacts(artifacts)
        return dict(state.payload["artifact_hashes"])

    def _family_artifacts(self) -> dict[str, Any]:
        return {
            "family-static-markdown": self._read_artifact(
                "family-static-markdown", graph=False
            ),
            "family-incremental-markdown": self._read_artifact(
                "family-incremental-markdown", graph=False
            ),
            "one-shot-family-skillgraph": self._read_artifact(
                "one-shot-family-skillgraph", graph=True
            ),
            "batch-refine-skillgraph": self._read_artifact(
                "batch-refine-skillgraph", graph=True
            ),
            "incremental-skillgraph": self._read_artifact(
                "incremental-skillgraph", graph=True
            ),
        }

    def _author_test_baselines(self, task_ids: Sequence[str]) -> dict[str, str]:
        lookup = _task_lookup()
        artifact_path = self.paths.artifacts / "per-task-static-markdown.json"
        usage_path = self.paths.records / "per-task-static-authoring.json"
        baselines: dict[str, str] = (
            json.loads(artifact_path.read_text(encoding="utf-8"))
            if artifact_path.exists()
            else {}
        )
        usage: dict[str, Any] = (
            json.loads(usage_path.read_text(encoding="utf-8"))
            if usage_path.exists()
            else {}
        )
        for task_id in task_ids:
            task = lookup[task_id]
            payload = {
                "task_id": task_id,
                "public_prompt": task["task_request"],
                "tool_signatures": task["available_tools"],
                "initial_state": task["initial_state"],
            }
            prompt = _artifact_prompt("per-task-static-markdown", payload)
            prompt_sha = hashlib.sha256(prompt.encode()).hexdigest()
            if task_id in baselines:
                validate_markdown_artifact(baselines[task_id])
                provenance = usage.get(task_id, {})
                expected = {
                    "status": "generated",
                    "model": AUTHOR_MODEL,
                    "prompt_sha256": prompt_sha,
                    "artifact_sha256": artifact_sha256(baselines[task_id]),
                }
                if any(provenance.get(key) != value for key, value in expected.items()):
                    raise RuntimeError(
                        f"Cached per-task baseline lacks valid provenance: {task_id}"
                    )
                continue
            markdown, record = _author_text(self.author, prompt)
            validate_markdown_artifact(markdown)
            baselines[task_id] = markdown
            usage[task_id] = {
                "status": "generated",
                "model": AUTHOR_MODEL,
                "prompt_sha256": prompt_sha,
                "artifact_sha256": artifact_sha256(markdown),
                "usage": record,
            }
            atomic_write(
                artifact_path,
                json.dumps(baselines, ensure_ascii=False, indent=2) + "\n",
            )
            atomic_write(
                usage_path,
                json.dumps(usage, ensure_ascii=False, indent=2) + "\n",
            )
        return baselines

    def run_sealed_test(self) -> dict[str, dict[str, list[dict[str, Any]]]]:
        state = ExperimentState.load(self.paths.state)
        self._bind_or_verify_configuration(state)
        actual_hashes = {
            name: artifact_sha256(artifact)
            for name, artifact in self._family_artifacts().items()
        }
        expected_hashes = {
            name: digest
            for name, digest in state.payload.get("artifact_hashes", {}).items()
            if name != "per-task-static-markdown"
        }
        if actual_hashes != expected_hashes:
            raise RuntimeError("Family artifacts differ from their frozen hashes")
        if state.payload["phase"] == "complete":
            raise RuntimeError("Sealed test has already opened and completed")
        if state.payload["phase"] == "artifacts_frozen":
            state.open_test()
        elif state.payload["phase"] not in {"test_open", "test_ready", "test_running"}:
            raise RuntimeError(
                f"Cannot resume sealed test from {state.payload['phase']!r}"
            )
        manifest = self._manifest()
        task_ids = [task["task_id"] for task in manifest["splits"]["test"]]
        baselines = self._author_test_baselines(task_ids)
        baseline_hash = artifact_sha256(baselines)
        frozen_baseline = state.payload["artifact_hashes"].get(
            "per-task-static-markdown"
        )
        if frozen_baseline is not None and frozen_baseline != baseline_hash:
            raise RuntimeError(
                "Per-task static baselines differ from their sealed hash"
            )
        if frozen_baseline is None:
            state.payload["artifact_hashes"]["per-task-static-markdown"] = baseline_hash
            state.payload["phase"] = "test_ready"
            state._save()
        family = self._family_artifacts()
        arm_artifacts: dict[str, tuple[Any, bool]] = {
            "no-skill": (None, False),
            "family-static-markdown": (family["family-static-markdown"], False),
            "family-incremental-markdown": (
                family["family-incremental-markdown"],
                False,
            ),
            "one-shot-family-skillgraph": (family["one-shot-family-skillgraph"], True),
            "batch-refine-skillgraph": (family["batch-refine-skillgraph"], True),
            "incremental-skillgraph": (family["incremental-skillgraph"], True),
        }
        checkpoint = self.paths.evaluations / "sealed-test.json"
        results: dict[str, dict[str, list[dict[str, Any]]]] = (
            json.loads(checkpoint.read_text(encoding="utf-8"))
            if checkpoint.exists()
            else {arm: {task_id: [] for task_id in task_ids} for arm in ARMS}
        )
        schedule = [
            (task_id, repetition, arm)
            for task_id in task_ids
            for repetition in range(5)
            for arm in ARMS
        ]
        random.Random(91_731).shuffle(schedule)
        state.payload["phase"] = "test_running"
        state.payload["test_schedule_sha256"] = hashlib.sha256(
            json.dumps(schedule).encode()
        ).hexdigest()
        start_index = int(state.payload.get("next_schedule_index", 0))
        state._save()
        for index in range(start_index, len(schedule)):
            task_id, repetition, arm = schedule[index]
            if any(
                item.get("_sealed_schedule_index") == index
                for item in results[arm][task_id]
            ):
                state.payload["next_schedule_index"] = index + 1
                state._save()
                continue
            if arm == "per-task-static-markdown":
                artifact, graph = baselines[task_id], False
            else:
                artifact, graph = arm_artifacts[arm]
            observation = self.evaluator.evaluate(
                [task_id],
                artifact,
                graph=graph,
                repetitions=1,
                label=f"sealed-{index:03d}-{arm}-{task_id}-r{repetition}",
            )
            for item in observation.get(task_id, []):
                stamped = copy.deepcopy(item)
                stamped["_sealed_schedule_index"] = index
                results[arm][task_id].append(stamped)
            atomic_write(
                checkpoint,
                json.dumps(results, ensure_ascii=False, indent=2) + "\n",
            )
            state.payload["next_schedule_index"] = index + 1
            state._save()
        missing = {
            f"{arm}:{task_id}": 5 - len(results[arm][task_id])
            for arm in ARMS
            for task_id in task_ids
            if len(results[arm][task_id]) != 5
        }
        state.payload["missing_test_observations"] = missing
        state.payload["phase"] = "complete" if not missing else "test_incomplete"
        state._save()
        return results

    def build_report(self) -> dict[str, Any]:
        state = ExperimentState.load(self.paths.state)
        if state.payload["phase"] not in {"complete", "test_incomplete"}:
            raise RuntimeError("Report requires a finished sealed test schedule")
        evaluations = json.loads(
            (self.paths.evaluations / "sealed-test.json").read_text(encoding="utf-8")
        )
        scores = {
            arm: _score_map(task_results) for arm, task_results in evaluations.items()
        }
        missing = dict(state.payload.get("missing_test_observations", {}))
        primary = (
            {
                "conclusion": "missing_observations_no_claim",
                "missing_observations": missing,
            }
            if missing
            else primary_comparison(
                scores["incremental-skillgraph"],
                scores["per-task-static-markdown"],
            )
        )
        secondary_pairs = {
            "execution_feedback": (
                "incremental-skillgraph",
                "one-shot-family-skillgraph",
            ),
            "sequential_minimal_edits": (
                "incremental-skillgraph",
                "batch-refine-skillgraph",
            ),
            "markdown_incremental": (
                "family-incremental-markdown",
                "family-static-markdown",
            ),
            "graph_system_vs_markdown": (
                "incremental-skillgraph",
                "family-incremental-markdown",
            ),
        }
        secondary = (
            {}
            if missing
            else {
                label: primary_comparison(scores[left], scores[right], seed=100 + index)
                for index, (label, (left, right)) in enumerate(secondary_pairs.items())
            }
        )
        arm_metrics = {}
        for arm, task_results in evaluations.items():
            observations = [item for values in task_results.values() for item in values]
            arm_metrics[arm] = {
                "observations": len(observations),
                "mean_score": (
                    statistics.fmean(float(item["score"]) for item in observations)
                    if observations
                    else None
                ),
                "pass_rate": (
                    statistics.fmean(bool(item.get("passed")) for item in observations)
                    if observations
                    else None
                ),
                "max_step_rate": (
                    statistics.fmean(
                        int(item.get("steps", 0)) >= 20 for item in observations
                    )
                    if observations
                    else None
                ),
                "tool_calls": sum(
                    int(item.get("num_tool_calls", 0)) for item in observations
                ),
                "student_input_tokens": sum(
                    int(item.get("input_tokens", 0)) for item in observations
                ),
                "student_output_tokens": sum(
                    int(item.get("output_tokens", 0)) for item in observations
                ),
                "inference_cost": sum(
                    float(item.get("cost") or 0.0) for item in observations
                ),
                "worst_task": (
                    min(
                        (
                            (
                                task,
                                statistics.fmean(
                                    float(item["score"]) for item in values
                                ),
                            )
                            for task, values in task_results.items()
                            if values
                        ),
                        key=lambda pair: pair[1],
                    )
                    if observations
                    else None
                ),
            }
        graphs = {
            name: validate_graph(self._read_artifact(name, graph=True))
            | {"version": int(self._read_artifact(name, graph=True)["version"])}
            for name in (
                "one-shot-family-skillgraph",
                "batch-refine-skillgraph",
                "incremental-skillgraph",
            )
        }
        optimization_path = self.paths.records / "optimization-summary.json"
        optimization = (
            json.loads(optimization_path.read_text(encoding="utf-8"))
            if optimization_path.exists()
            else {}
        )
        rounds = list(optimization.get("incremental_graph_rounds", [])) + list(
            optimization.get("incremental_markdown_rounds", [])
        )
        decisions = [
            item.get("gate", {}).get("decision")
            for item in rounds
            if isinstance(item.get("gate"), Mapping)
        ]
        author_records = [optimization]
        for record_path in (
            self.paths.records / "initial-authoring.json",
            self.paths.records / "per-task-static-authoring.json",
        ):
            if record_path.exists():
                author_records.append(
                    json.loads(record_path.read_text(encoding="utf-8"))
                )
        actor_train_totals = _merge_totals(
            *(round_record.get("train_rollout_totals", {}) for round_record in rounds)
        )
        validation_totals = _merge_totals(
            *(
                round_record.get("validation_rollout_totals", {})
                for round_record in rounds
            )
        )
        analyzer_totals = _merge_totals(
            *(
                _numeric_totals(
                    round_record.get("author_usage", {}).get(
                        "analyzer", round_record.get("author_usage", {})
                    )
                )
                for round_record in rounds
            )
        )
        curator_totals = _merge_totals(
            *(
                _numeric_totals(round_record.get("author_usage", {}).get("curator", {}))
                for round_record in rounds
            )
        )
        batch_refine_totals = _numeric_totals(
            optimization.get("batch_refine_usage", {})
        )
        report = {
            "schema_version": 1,
            "primary": primary,
            "secondary_exploratory": secondary,
            "arms": arm_metrics,
            "graph_complexity": graphs,
            "optimization": {
                "accepted_edits": decisions.count("ACCEPT"),
                "rejected_edits": decisions.count("REJECT"),
                "no_edit_rounds": sum(item.get("gate") == "NO_EDIT" for item in rounds),
                "actor_train": actor_train_totals,
                "paired_validation": validation_totals,
                "analyzer": analyzer_totals,
                "curator": curator_totals,
                "batch_refine": batch_refine_totals,
                "grand_total": _merge_totals(
                    actor_train_totals,
                    validation_totals,
                    analyzer_totals,
                    curator_totals,
                    batch_refine_totals,
                ),
                "all_authoring_totals": _numeric_totals(author_records),
            },
            "artifact_hashes": state.payload["artifact_hashes"],
            "caveats": [
                "Secondary comparisons are exploratory and are not independent primary claims.",
                "Graph versus Markdown combines representation and explicit execution semantics.",
                "Test tasks are held out from this optimization flow, but are public benchmark tasks that may have been run historically.",
            ],
        }
        atomic_write(
            self.paths.report, json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        )
        return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-dir", type=Path, default=ROOT / "runs" / "family-skillgraph-v1"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("select", help="Freeze the family manifest")
    subparsers.add_parser("author", help="Author the family-level initial artifacts")
    subparsers.add_parser("optimize", help="Run both five-round incremental optimizers")
    subparsers.add_parser("freeze", help="Hash and freeze all family artifacts")
    subparsers.add_parser("test", help="Open and execute the sealed test exactly once")
    subparsers.add_parser("report", help="Build the task-level bootstrap report")
    subparsers.add_parser("run", help="Run select through report in order")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    run_dir = args.run_dir.resolve()
    if args.command == "select":
        manifest = write_family_manifest(run_dir / "manifest.json")
        print(json.dumps(manifest["counts"], indent=2))
        return 0
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    paths = FamilyPaths(run_dir)
    author = DeepSeekAuthor()
    evaluator = AutomationBenchEvaluator(paths.evaluations / "raw")
    experiment = FamilyExperiment(paths, author, evaluator)
    if args.command == "author":
        result = experiment.author_initial()
    elif args.command == "optimize":
        result = experiment.optimize()
    elif args.command == "freeze":
        result = experiment.freeze()
    elif args.command == "test":
        result = {
            arm: sum(len(items) for items in tasks.values())
            for arm, tasks in experiment.run_sealed_test().items()
        }
    elif args.command == "report":
        result = experiment.build_report()
    elif args.command == "run":
        write_family_manifest(paths.manifest)
        experiment.author_initial()
        experiment.optimize()
        experiment.freeze()
        experiment.run_sealed_test()
        result = experiment.build_report()
    else:  # pragma: no cover - argparse enforces the choices
        raise AssertionError(args.command)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
