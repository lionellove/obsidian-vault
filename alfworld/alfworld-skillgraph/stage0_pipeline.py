"""Paused, auditable Stage 0 orchestration state machine.

The pipeline is deliberately injectable.  Unit tests can provide a fake
semantic client and an episode runner; a real CLI run must satisfy explicit
human/data/credential gates before any live episode is unlocked.
"""

from __future__ import annotations

import copy
import csv
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from stage0_artifacts import ArtifactSafetyError, ArtifactWriter
from stage0_core import (
    FAMILIES,
    canonical,
    canonical_task_id,
    classify_task_family,
    diff_skill,
    paired_outcomes,
    render_skill,
    sha256,
    sha256_file,
    task_group_key,
    task_id_key,
    validate_skill,
)
from stage0_episode import EpisodeRunner
from stage0_evolution import EvolutionEngine, EvolutionResult, NO_ROOT_CAUSE
from stage0_executor import Executor
from stage0_format import normalize_json_response
from stage0_llm import MODEL_ID
from stage0_metrics import (
    evaluate_calibration_gate,
    evaluate_stage0_gate,
    family_success_vector,
    paired_rows,
    skill_render_metrics,
    summarize_episode_metrics,
)
from stage0_run import ENVIRONMENT_SEED, SAMPLE_SEED, balanced_validation_conditions, existing_task_keys, resolve_train_root, sample
from stage0_s0 import S0GenerationResult, S0Generator
from stage0_verifier import CandidateResult


PIPELINE_VERSION = "stage0-pipeline-0.1"
MANIFEST_NAMES = ("calibration", "evolution", "patch_validation")
CONDITIONS = ("baseline", "structured_patch", "full_rewrite")


def _plain(value: Any) -> Any:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _plain(value.to_dict())
    if isinstance(value, dict):
        return {str(key): _plain(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(child) for child in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _now(clock: Callable[[], float] | None = None) -> str:
    if clock is not None:
        value = clock()
        if isinstance(value, str):
            return value
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat().replace("+00:00", "Z")
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class Stage0ArtifactLayout:
    """The frozen §16 directory layout and exact-byte hash helpers."""

    DIRECTORIES = (
        "manifests",
        "s0",
        "trajectories/calibration",
        "trajectories/evolution",
        "trajectories/validation",
        "ir",
        "candidates/structured_patch",
        "candidates/full_rewrite",
        "verifier",
        "audit",
        "report",
    )

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def create(self) -> dict[str, Path]:
        self.root.mkdir(parents=True, exist_ok=True)
        for relative in self.DIRECTORIES:
            (self.root / relative).mkdir(parents=True, exist_ok=True)
        return {"root": self.root, **{relative: self.root / relative for relative in self.DIRECTORIES}}

    def path(self, relative: str | Path) -> Path:
        return self.root / relative

    def _write_bytes(self, relative: str | Path, payload: bytes) -> Path:
        path = self.path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        path.with_name(path.name + ".sha256").write_text(digest + "\n", encoding="ascii")
        # Keep the plan's human-friendly ``foo.sha256`` convention alongside
        # the unambiguous ``foo.json.sha256`` form used by ArtifactWriter.
        if path.suffix:
            path.with_name(path.stem + ".sha256").write_text(digest + "\n", encoding="ascii")
        return path

    def _assert_safe(self, value: Any) -> None:
        secret = os.environ.get("DEEPSEEK_API_KEY", "")
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).casefold() in {"api_key", "apikey", "authorization", "access_token"}:
                    raise ArtifactSafetyError("credential field cannot be written to Stage 0 artifacts")
                self._assert_safe(child)
        elif isinstance(value, list):
            for child in value:
                self._assert_safe(child)
        elif isinstance(value, str) and secret and secret in value:
            raise ArtifactSafetyError("API key cannot be written to Stage 0 artifacts")

    def write_text(self, relative: str | Path, value: str) -> Path:
        if not isinstance(value, str):
            raise TypeError("artifact text must be a string")
        self._assert_safe(value)
        return self._write_bytes(relative, value.encode("utf-8"))

    def write_json(self, relative: str | Path, value: Any) -> Path:
        plain = _plain(value)
        self._assert_safe(plain)
        payload = (json.dumps(plain, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        return self._write_bytes(relative, payload)

    def write_jsonl(self, relative: str | Path, values: Iterable[Any]) -> Path:
        values = list(values)
        self._assert_safe(_plain(values))
        payload = b"".join(
            (json.dumps(_plain(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
            for value in values
        )
        return self._write_bytes(relative, payload)

    def hash_file(self, relative: str | Path) -> str:
        return sha256_file(self.path(relative))


def _validate_manifests(manifests: dict[str, list[str]], expected_size: int) -> dict[str, list[str]]:
    if set(manifests) != set(MANIFEST_NAMES):
        raise ValueError("manifests must contain calibration, evolution, and patch_validation")
    normalized: dict[str, list[str]] = {}
    all_ids: set[str] = set()
    groups: dict[str, set[str]] = {}
    for name in MANIFEST_NAMES:
        values = manifests[name]
        if not isinstance(values, list) or len(values) != expected_size:
            raise ValueError(f"{name} manifest must contain exactly {expected_size} tasks")
        ids = [canonical_task_id(value) for value in values]
        keys = {task_id_key(value) for value in ids}
        if len(keys) != len(ids) or all_ids & keys:
            raise ValueError("manifest task IDs must be unique across all phases")
        all_ids.update(keys)
        phase_groups = {task_group_key(value) for value in ids}
        for other_name, other_groups in groups.items():
            if phase_groups & other_groups:
                raise ValueError(f"task groups overlap between {name} and {other_name}")
        groups[name] = phase_groups
        normalized[name] = sorted(ids, key=str.casefold)
    if expected_size == 18:
        for name, values in normalized.items():
            family_counts = Counter(classify_task_family(value) for value in values)
            if set(family_counts) != set(FAMILIES) or any(family_counts[family] != 3 for family in FAMILIES):
                raise ValueError(f"production {name} manifest must contain exactly 3 tasks per family")
    return normalized


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


class Stage0Pipeline:
    """Prepare → human approval → calibration → evolution → validation."""

    def __init__(
        self,
        run_dir: str | Path,
        *,
        client: Any = None,
        environment_factory: Callable[[str, str, int], Any] | None = None,
        episode_runner_factory: Callable[[dict, Any, str, str], dict] | None = None,
        clock: Callable[[], float] | None = None,
        repo_root: str | Path | None = None,
        data_root: str | Path | None = None,
        task_manifests: dict[str, list[str]] | None = None,
        denylist: Iterable[str] | None = None,
        testing_plan_size: int = 18,
        environment_seed: int = ENVIRONMENT_SEED,
        model_alias: str = MODEL_ID,
        code_fingerprint: str | None = None,
        data_fingerprint: str | None = None,
    ) -> None:
        if isinstance(testing_plan_size, bool) or not isinstance(testing_plan_size, int) or not 1 <= testing_plan_size <= 18:
            raise ValueError("testing_plan_size must be in [1, 18]")
        if testing_plan_size != 18 and task_manifests is None:
            raise ValueError("reduced testing plans require explicit task_manifests")
        self.layout = Stage0ArtifactLayout(run_dir)
        self.client = client
        self.environment_factory = environment_factory
        self.episode_runner_factory = episode_runner_factory
        self.clock = clock
        self.repo_root = Path(repo_root) if repo_root is not None else self.layout.root.parent
        self.data_root = Path(data_root) if data_root is not None else None
        self.task_manifests = copy.deepcopy(task_manifests)
        self.denylist = set(denylist or [])
        self.testing_plan_size = testing_plan_size
        self.environment_seed = environment_seed
        self.model_alias = model_alias
        self.code_fingerprint = code_fingerprint or self._code_state_fingerprint()
        self.data_fingerprint = data_fingerprint

    def _code_state_fingerprint(self) -> str:
        try:
            commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repo_root, text=True, stderr=subprocess.DEVNULL).strip()
            dirty = subprocess.check_output(["git", "diff", "--no-ext-diff"], cwd=self.repo_root, text=True, stderr=subprocess.DEVNULL)
            return sha256(canonical({"commit": commit, "dirty_diff": dirty}))
        except (OSError, subprocess.CalledProcessError):
            return sha256(PIPELINE_VERSION)

    def _state(self) -> dict[str, Any]:
        path = self.layout.path("state.json")
        return _read_json(path) if path.exists() else {}

    def _write_state(self, state: dict[str, Any]) -> None:
        self.layout.write_json("state.json", state)

    def status(self) -> dict[str, Any]:
        state = self._state()
        if not state:
            return {"status": "missing", "run_dir": str(self.layout.root)}
        return state

    def _record_hashes(self) -> dict[str, str]:
        result: dict[str, str] = {}
        if not self.layout.root.exists():
            return result
        for path in sorted(self.layout.root.rglob("*")):
            if not path.is_file() or path.name.endswith(".sha256") or path.name == "state.json":
                continue
            result[path.relative_to(self.layout.root).as_posix()] = sha256_file(path)
        return result

    def _manifest_payload(self, manifests: dict[str, list[str]]) -> None:
        deny_keys = sorted(task_id_key(value) for value in self.denylist)
        self.layout.write_json("manifests/denylist.json", {"task_ids": deny_keys, "count": len(deny_keys), "environment_seed": self.environment_seed})
        for name, values in manifests.items():
            self.layout.write_json(
                f"manifests/{name}.json",
                {
                    "task_ids": values,
                    "count": len(values),
                    "sample_seed": SAMPLE_SEED,
                    "environment_seed": self.environment_seed,
                    "group_keys": [task_group_key(value) for value in values],
                },
            )

    def _load_s0(self) -> dict:
        skill = _read_json(self.layout.path("s0/skill_package.json"))
        errors = validate_skill(skill, enforce_budget=True)
        if errors:
            raise RuntimeError("frozen S0 is invalid: " + "; ".join(errors))
        return skill

    def prepare(self) -> dict[str, Any]:
        if self.client is None:
            raise RuntimeError("prepare requires an injected semantic client or a configured live client")
        self.layout.create()
        if self.task_manifests is None:
            if self.data_root is None:
                raise RuntimeError("prepare requires data_root when task_manifests are not supplied")
            train_root = resolve_train_root(self.data_root)
            self.denylist = existing_task_keys(self.repo_root, train_root=train_root)
            manifests = sample(train_root, self.denylist, seed=SAMPLE_SEED)
        else:
            manifests = self.task_manifests
        manifests = _validate_manifests(manifests, self.testing_plan_size)
        deny_keys = {task_id_key(value) for value in self.denylist}
        if any(task_id_key(task_id) in deny_keys for values in manifests.values() for task_id in values):
            raise RuntimeError("frozen manifest contains a denylisted task ID")
        self.task_manifests = manifests
        self._manifest_payload(manifests)
        if self.data_fingerprint is None:
            self.data_fingerprint = sha256(canonical({"data_root": str(self.data_root) if self.data_root else None, "manifests": manifests, "denylist": sorted(self.denylist)}))
        generator = S0Generator(self.client)
        generated = generator.generate()
        self.layout.write_text("s0/generation_prompt.txt", generated.generation_prompt)
        self.layout.write_json("s0/raw_response.json", generated.raw_response)
        self.layout.write_json(
            "s0/gate_packet.json",
            {"status": generated.status, "checklist": generated.gate_checklist, "feedback": generated.gate_feedback, "attempts": generated.attempts},
        )
        if generated.skill is not None:
            self.layout.write_json("s0/skill_package.json", generated.skill)
            self.layout.write_text("s0/rendered_skill.md", generated.rendered_skill or render_skill(generated.skill))
        self.layout.write_json("s0/request_records.json", generated.request_records)
        state = {
            "pipeline_version": PIPELINE_VERSION,
            "run_dir": str(self.layout.root),
            "status": generated.status,
            "created_at": _now(self.clock),
            "environment_seed": self.environment_seed,
            "model_alias": self.model_alias,
            "code_fingerprint": self.code_fingerprint,
            "data_fingerprint": self.data_fingerprint,
            "s0_skill_hash": generated.skill_hash,
            "s0_gate_checklist": generated.gate_checklist,
            "s0_frozen": False,
            "manifest_hashes": {name: sha256_file(self.layout.path(f"manifests/{name}.json")) for name in MANIFEST_NAMES},
            "denylist_hash": sha256_file(self.layout.path("manifests/denylist.json")),
            "artifact_hashes": self._record_hashes(),
            "errors": [],
        }
        self._write_state(state)
        return state

    def approve(self, checklist: dict[str, bool], *, auditor: str, timestamp: str | None = None) -> dict[str, Any]:
        state = self._state()
        if state.get("status") != "awaiting_human_gate":
            raise RuntimeError("approve requires awaiting_human_gate state")
        if not isinstance(auditor, str) or not auditor.strip():
            raise ValueError("auditor is required")
        expected = {key: bool(value) for key, value in state.get("s0_gate_checklist", {}).items()}
        if set(checklist) != {"schema_valid", "no_instance_leakage", "six_family_applicable", "no_contradiction", "within_budget"}:
            raise ValueError("human gate requires exactly five checklist fields")
        if any(not isinstance(value, bool) for value in checklist.values()) or checklist != expected or not all(checklist.values()):
            raise ValueError("human gate checklist is not fully true or does not match generated S0")
        skill = self._load_s0()
        if state.get("s0_skill_hash") != sha256(canonical(skill)):
            raise RuntimeError("S0 hash changed before approval")
        approval = {"checklist": copy.deepcopy(checklist), "auditor": auditor, "timestamp": timestamp or _now(self.clock)}
        self.layout.write_json("audit/human_gate.json", approval)
        state.update(
            {
                "status": "approved",
                "approved_at": approval["timestamp"],
                "s0_frozen": True,
                "human_gate": approval,
                "artifact_hashes": self._record_hashes(),
            }
        )
        self._write_state(state)
        return state

    def _check_frozen(self, *, require_approved: bool = True) -> dict[str, Any]:
        state = self._state()
        if require_approved and state.get("status") != "approved":
            raise RuntimeError(f"run requires approved state, got {state.get('status')}")
        if state.get("code_fingerprint") != self.code_fingerprint or state.get("data_fingerprint") != self.data_fingerprint or state.get("model_alias") != self.model_alias:
            raise RuntimeError("frozen code/data/model fingerprint mismatch")
        for relative, digest in state.get("artifact_hashes", {}).items():
            path = self.layout.path(relative)
            if not path.is_file() or sha256_file(path) != digest:
                raise RuntimeError(f"frozen artifact hash mismatch: {relative}")
        return state

    def resume(self, *, continue_run: bool = False) -> dict[str, Any]:
        state = self._check_frozen(require_approved=False)
        if state.get("status") not in {"approved", "running"}:
            raise RuntimeError(f"resume requires approved or running state, got {state.get('status')}")
        if continue_run:
            return self.run()
        return state

    def _seed_for(self, task_id: str, condition: str, index: int) -> int:
        digest = hashlib.sha256(f"{self.environment_seed}|{task_id}|{condition}|{index}".encode("utf-8")).hexdigest()
        return int(digest[:8], 16)

    def _episode(self, skill: dict, task_id: str, condition: str, phase: str, index: int) -> dict:
        if self.environment_factory is None:
            raise RuntimeError("environment_factory is required for episode execution")
        seed = self._seed_for(task_id, condition, index)
        env = self.environment_factory(task_id, condition, seed)
        if self.episode_runner_factory is not None:
            row = self.episode_runner_factory(skill, env, task_id, condition)
        else:
            executor = Executor(client=self.client, skill_text=render_skill(skill), skill_hash=sha256(canonical(skill)))
            row = EpisodeRunner(env, executor, max_steps=50).run(task_id=task_id)
        if not isinstance(row, dict):
            raise RuntimeError("episode runner must return a dictionary")
        result = copy.deepcopy(row)
        result.setdefault("task_id", task_id)
        result["condition"] = condition
        result["phase"] = phase
        result["seed"] = seed
        result.setdefault("family", classify_task_family(task_id) or "unknown")
        return result

    def _write_trajectory(self, phase: str, rows: list[dict], label: str) -> None:
        self.layout.write_jsonl(f"trajectories/{phase}/{label}.jsonl", rows)

    def _testing_schedule(self, task_ids: list[str]) -> list[dict[str, Any]]:
        if len(task_ids) == 18:
            return balanced_validation_conditions(task_ids, seed=SAMPLE_SEED)
        # Reduced offline plans cycle the six public orderings; production is
        # still forced through balanced_validation_conditions above.
        import itertools

        orders = list(itertools.permutations(CONDITIONS))
        return [{"task_id": task_id, "condition_order": list(orders[index % len(orders)])} for index, task_id in enumerate(task_ids)]

    def validation_schedule(self, task_ids: list[str]) -> list[dict[str, Any]]:
        """Return the frozen balanced condition schedule for validation tasks."""

        return self._testing_schedule(task_ids)

    def _write_code_state(self, *, started: str, ended: str | None, errors: list[str], request_records: list[dict]) -> None:
        try:
            commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repo_root, text=True, stderr=subprocess.DEVNULL).strip()
            dirty = subprocess.check_output(["git", "diff", "--no-ext-diff"], cwd=self.repo_root, text=True, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.CalledProcessError):
            commit, dirty = "unknown", ""
        state = self._state()
        skill = self._load_s0()
        payload = {
            "git_commit": commit,
            "dirty_worktree_diff_hash": sha256(dirty),
            "python": sys.version,
            "dependencies": [],
            "alfworld_data_version": str(self.data_root) if self.data_root else None,
            "evaluator": "EpisodeRunner",
            "prompt_hash": sha256_file(self.layout.path("s0/generation_prompt.txt")) if self.layout.path("s0/generation_prompt.txt").exists() else None,
            "schema_hash": sha256(canonical({"schema_version": "0.1"})),
            "renderer_hash": sha256(render_skill(skill)),
            "skill_hash": sha256(canonical(skill)),
            "manifest_hashes": state.get("manifest_hashes", {}),
            "model_alias": self.model_alias,
            "system_fingerprints": sorted({record.get("system_fingerprint") for record in request_records if record.get("system_fingerprint")}),
            "request_parameters": [record.get("request_body", {}) for record in request_records],
            "started_at": started,
            "ended_at": ended,
            "errors": list(errors),
            "retries": sum(1 for error in errors if "retry" in error.casefold()),
        }
        self.layout.write_json("code_state.json", payload)

    def _write_report(self, gate: dict[str, Any], metrics: dict[str, Any]) -> None:
        lines = [
            "# Stage 0 report",
            "",
            f"Go/no-go: {'GO' if gate.get('go') else 'NO-GO'}",
            "",
            "This report is exploratory and does not claim statistical significance.",
            "",
            "## Gate conditions",
            "",
        ]
        for key, value in gate.get("conditions", {}).items():
            lines.append(f"- {key}: {'PASS' if value else 'FAIL'}")
        lines.extend(["", "## Metrics", "", "```json", json.dumps(_plain(metrics), ensure_ascii=False, indent=2, sort_keys=True), "```", ""])
        self.layout.write_text("report/stage0_report.md", "\n".join(lines))

    def _write_audit_packet(self, evolution: EvolutionResult | None) -> None:
        if evolution is None:
            packet = {"audit_status": "no_evolution", "candidates": [], "validation_scores_hidden": True}
        else:
            candidates = []
            for candidate in (evolution.structured_candidate, evolution.rewrite_candidate):
                if candidate is None:
                    continue
                value = candidate.final_ir if isinstance(candidate.final_ir, dict) else {}
                if isinstance(value, dict):
                    value = copy.deepcopy(value)
                    value.pop("method", None)
                    value.pop("generator", None)
                    if "semantic_patch" in value and len(value) == 1:
                        value = value["semantic_patch"]
                    elif "full_rewrite" in value and len(value) == 1:
                        value = value["full_rewrite"]
                    if isinstance(value, dict):
                        if "rewritten_skill_package" in value:
                            value["candidate_skill_package"] = value.pop("rewritten_skill_package")
                        if "change_manifest" in value:
                            value["changes"] = value.pop("change_manifest")
                candidates.append({"candidate_id": f"candidate_{len(candidates) + 1}", "candidate_semantics": value})
            packet = {
                "audit_status": "exploratory_single_audit",
                "auditor_count": 1,
                "rubric_version": "stage0-8-item",
                "failures": evolution.failures,
                "preservations": evolution.preservations,
                "root_cause": evolution.root_cause,
                "candidates": candidates,
                "validation_scores_hidden": True,
                "method_labels_hidden": True,
                "expert_plan_included": False,
            }
        self.layout.write_json("audit/blinded_packet.json", packet)

    def run(self) -> dict[str, Any]:
        state = self._check_frozen(require_approved=False)
        if state.get("status") not in {"approved", "running"}:
            raise RuntimeError(f"run requires approved state, got {state.get('status')}")
        started = _now(self.clock)
        errors: list[str] = []
        request_records: list[dict] = []
        s0_records_path = self.layout.path("s0/request_records.json")
        if s0_records_path.exists():
            loaded_s0_records = _read_json(s0_records_path)
            if isinstance(loaded_s0_records, list):
                request_records.extend(record for record in loaded_s0_records if isinstance(record, dict))
        manifests = {name: _read_json(self.layout.path(f"manifests/{name}.json"))["task_ids"] for name in MANIFEST_NAMES}
        s0 = self._load_s0()
        state["status"] = "running"
        state["started_at"] = started
        self._write_state(state)
        calibration_rows: list[dict] = []
        try:
            for index, task_id in enumerate(manifests["calibration"]):
                calibration_rows.append(self._episode(s0, task_id, "baseline", "calibration", index))
        except Exception as exc:
            errors.append(repr(exc))
        self._write_trajectory("calibration", calibration_rows, "episodes")
        calibration_gate = evaluate_calibration_gate(sum(bool(row.get("success")) for row in calibration_rows), total=len(manifests["calibration"]))
        self.layout.write_json("trajectories/calibration/summary.json", calibration_gate)
        if calibration_gate["status"] != "proceed":
            state.update({"status": calibration_gate["status"], "calibration_gate": calibration_gate, "ended_at": _now(self.clock), "errors": errors, "artifact_hashes": self._record_hashes()})
            self._write_code_state(started=started, ended=state["ended_at"], errors=errors, request_records=request_records)
            self._write_report(calibration_gate, {"calibration": calibration_gate})
            self._write_state(state)
            return state

        evolution_rows: list[dict] = []
        try:
            for index, task_id in enumerate(manifests["evolution"]):
                evolution_rows.append(self._episode(s0, task_id, "baseline", "evolution", index))
        except Exception as exc:
            errors.append(repr(exc))
        self._write_trajectory("evolution", evolution_rows, "episodes")
        evolution_result: EvolutionResult | None = None
        try:
            evolution_result = EvolutionEngine(self.client).run(evolution_rows, s0)
            ArtifactWriter(self.layout.root).write(evolution_result)
            request_records.extend(evolution_result.request_records)
        except Exception as exc:
            errors.append(repr(exc))
        self._write_audit_packet(evolution_result)

        patch_candidate = evolution_result.structured_candidate if evolution_result else None
        rewrite_candidate = evolution_result.rewrite_candidate if evolution_result else None
        patch_skill = patch_candidate.structural_result.get("skill") if patch_candidate and patch_candidate.valid else None
        rewrite_skill = rewrite_candidate.structural_result.get("skill") if rewrite_candidate and rewrite_candidate.valid else None
        schedule = self._testing_schedule(manifests["patch_validation"])
        validation: dict[str, list[dict]] = {condition: [] for condition in CONDITIONS}
        for task_index, item in enumerate(schedule):
            for condition in item["condition_order"]:
                skill = s0 if condition == "baseline" else patch_skill if condition == "structured_patch" else rewrite_skill
                if skill is None:
                    validation[condition].append({"task_id": item["task_id"], "condition": condition, "skipped": True, "reason": "candidate_not_valid"})
                    continue
                try:
                    validation[condition].append(self._episode(skill, item["task_id"], condition, "validation", task_index))
                except Exception as exc:
                    errors.append(repr(exc))
                    validation[condition].append({"task_id": item["task_id"], "condition": condition, "skipped": True, "reason": repr(exc)})
        for condition, rows in validation.items():
            self._write_trajectory("validation", rows, condition)

        baseline_rows = [row for row in validation["baseline"] if not row.get("skipped")]
        patch_rows = [row for row in validation["structured_patch"] if not row.get("skipped")]
        rewrite_rows = [row for row in validation["full_rewrite"] if not row.get("skipped")]
        paired_patch = paired_rows(
            [{"task_id": row["task_id"], "success": bool(row.get("success"))} for row in baseline_rows],
            [{"task_id": row["task_id"], "success": bool(row.get("success"))} for row in patch_rows],
        ) if patch_skill is not None and len(patch_rows) == len(baseline_rows) else []
        paired_patch_summary = paired_patch[-1].get("summary", {}) if paired_patch and isinstance(paired_patch[-1], dict) else {}
        s0_words = skill_render_metrics(s0)["words"]
        patch_words = skill_render_metrics(patch_skill)["words"] if patch_skill else s0_words
        gate = evaluate_stage0_gate(
            calibration_successes=calibration_gate["successes"],
            calibration_total=calibration_gate["total"],
            root_cause=evolution_result.root_cause if evolution_result else {"status": NO_ROOT_CAUSE},
            structured_candidate=patch_candidate.to_dict() if patch_candidate else None,
            paired_summary=paired_patch_summary,
            s0_words=s0_words,
            structured_words=patch_words,
            structured_successes=sum(bool(row.get("success")) for row in patch_rows),
            rewrite_successes=sum(bool(row.get("success")) for row in rewrite_rows) if rewrite_skill else None,
            rewrite_candidate_valid=rewrite_skill is not None,
        )
        metrics = {
            "calibration": summarize_episode_metrics(calibration_rows),
            "evolution": summarize_episode_metrics(evolution_rows),
            "validation": {condition: summarize_episode_metrics(rows) for condition, rows in validation.items()},
            "family_success_vector": {condition: family_success_vector(rows) for condition, rows in validation.items()},
            "paired_structured": paired_patch,
            "gate": gate,
            "render": {"s0": skill_render_metrics(s0), "structured": skill_render_metrics(patch_skill) if patch_skill else None, "rewrite": skill_render_metrics(rewrite_skill) if rewrite_skill else None},
            "edit_distance": len(diff_skill(s0, patch_skill)) if patch_skill else None,
            "format_repairs": {"structured": patch_candidate.format_repairs if patch_candidate else [], "rewrite": rewrite_candidate.format_repairs if rewrite_candidate else []},
            "candidate_validity": {"structured": bool(patch_candidate and patch_candidate.valid), "rewrite": bool(rewrite_candidate and rewrite_candidate.valid)},
            "semantic_audit": {"structured": evolution_result.structured_verifier.to_dict() if evolution_result and evolution_result.structured_verifier else None, "rewrite": evolution_result.rewrite_verifier.to_dict() if evolution_result and evolution_result.rewrite_verifier else None},
        }
        self.layout.write_json("report/metrics.json", metrics)
        if paired_patch:
            with self.layout.path("report/paired_outcomes.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["task_id", "baseline_success", "candidate_success", "category"])
                writer.writeheader()
                for row in paired_patch[:-1]:
                    writer.writerow(row)
        self._write_report(gate, metrics)
        ended = _now(self.clock)
        self._write_code_state(started=started, ended=ended, errors=errors, request_records=request_records)
        state.update({"status": "completed", "ended_at": ended, "calibration_gate": calibration_gate, "stage0_gate": gate, "errors": errors, "artifact_hashes": self._record_hashes()})
        self._write_state(state)
        return state


__all__ = ["Stage0ArtifactLayout", "Stage0Pipeline"]
