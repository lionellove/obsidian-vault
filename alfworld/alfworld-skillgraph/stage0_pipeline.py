"""Paused, auditable Stage 0 orchestration state machine.

The pipeline is deliberately injectable.  Unit tests can provide a fake
semantic client and an episode runner; a real CLI run must satisfy explicit
human/data/credential gates before any live episode is unlocked.
"""

from __future__ import annotations

import copy
import csv
import hashlib
import importlib.metadata
import json
import os
import platform
import random
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from stage0_artifacts import ArtifactSafetyError, ArtifactWriter, assert_no_secrets, safe_plain
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
    estimate_api_cost,
    evaluate_calibration_gate,
    evaluate_stage0_gate,
    family_success_vector,
    paired_rows,
    skill_render_metrics,
    summarize_episode_metrics,
    pricing_metadata,
)
from stage0_run import ENVIRONMENT_SEED, SAMPLE_SEED, balanced_validation_conditions, existing_task_keys, resolve_train_root, sample
from stage0_s0 import S0GenerationResult, S0Generator, S0_GATE_FIELDS
from stage0_verifier import CandidateResult


PIPELINE_VERSION = "stage0-pipeline-0.1"
MANIFEST_NAMES = ("calibration", "evolution", "patch_validation")
CONDITIONS = ("baseline", "structured_patch", "full_rewrite")
AUDIT_RUBRIC_FIELDS = (
    "failure_ir_evidence",
    "root_cause_explanation",
    "scope_reusability",
    "non_skill_error_check",
    "representation_choice",
    "edit_coherence",
    "unsupported_new_rules",
    "preservation_integrity",
)


def _plain(value: Any) -> Any:
    return safe_plain(value)


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
        assert_no_secrets(value)

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

    def write_json_atomic(self, relative: str | Path, value: Any) -> Path:
        """Atomically persist checkpoint/state JSON with its byte hash."""

        plain = _plain(value)
        self._assert_safe(plain)
        payload = (json.dumps(plain, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        path = self.path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_bytes(payload)
        os.replace(temporary, path)
        digest = hashlib.sha256(payload).hexdigest()
        path.with_name(path.name + ".sha256").write_text(digest + "\n", encoding="ascii")
        if path.suffix:
            path.with_name(path.stem + ".sha256").write_text(digest + "\n", encoding="ascii")
        return path

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
        if testing_plan_size != 18 and task_manifests is None and not (Path(run_dir) / "manifests").is_dir():
            raise ValueError("reduced testing plans require explicit task_manifests")
        self.layout = Stage0ArtifactLayout(run_dir)
        existing_state: dict[str, Any] = {}
        state_path = self.layout.path("state.json")
        if state_path.is_file():
            try:
                loaded = _read_json(state_path)
                if isinstance(loaded, dict):
                    existing_state = loaded
            except (OSError, ValueError, TypeError):
                existing_state = {}
        self.client = client
        self.environment_factory = environment_factory
        self.episode_runner_factory = episode_runner_factory
        self.clock = clock
        frozen_config = existing_state.get("frozen_config", {}) if isinstance(existing_state.get("frozen_config"), dict) else {}
        saved_repo = existing_state.get("repo_root") or frozen_config.get("repo_root")
        saved_data = existing_state.get("data_root") or frozen_config.get("data_root")
        self.repo_root = Path(repo_root or saved_repo or self.layout.root.parent)
        self.data_root = Path(data_root or saved_data) if (data_root or saved_data) else None
        self.task_manifests = copy.deepcopy(task_manifests)
        self.denylist = set(denylist or [])
        self.testing_plan_size = int(frozen_config.get("testing_plan_size", testing_plan_size))
        self.environment_seed = int(existing_state.get("environment_seed", frozen_config.get("environment_seed", environment_seed)))
        self.model_alias = str(existing_state.get("model_alias", frozen_config.get("model_alias", model_alias)))
        self.code_fingerprint = code_fingerprint or self._code_state_fingerprint()
        self.data_fingerprint = data_fingerprint or existing_state.get("data_fingerprint")
        self._checkpoint_rows: dict[str, dict[str, Any]] = {}
        self._request_records: list[dict[str, Any]] = []
        self._request_record_keys: set[str] = set()

    def _code_state_snapshot(self) -> dict[str, Any]:
        """Capture committed, staged, unstaged, and untracked source state."""

        def git_output(command: list[str]) -> str:
            try:
                return subprocess.check_output(
                    command,
                    cwd=self.repo_root,
                    text=True,
                    stderr=subprocess.DEVNULL,
                )
            except (OSError, subprocess.CalledProcessError):
                return ""

        source_root = Path(__file__).resolve().parent
        files: dict[str, str] = {}
        for path in sorted(source_root.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts or path.suffix.casefold() not in {".py", ".md"}:
                continue
            try:
                files[path.relative_to(source_root).as_posix()] = sha256_file(path)
            except OSError:
                continue
        return {
            "head": git_output(["git", "rev-parse", "HEAD"]).strip() or "unknown",
            "unstaged_diff": sha256(git_output(["git", "diff", "--no-ext-diff", "--", str(source_root)])),
            "staged_diff": sha256(git_output(["git", "diff", "--cached", "--no-ext-diff", "--", str(source_root)])),
            "files": files,
        }

    def _code_state_fingerprint(self) -> str:
        return sha256(canonical(self._code_state_snapshot()))

    def code_fingerprint(self) -> str:
        """Public current code fingerprint used by resume and audit tests."""

        return self._code_state_fingerprint()

    def _state(self) -> dict[str, Any]:
        path = self.layout.path("state.json")
        if not path.exists():
            return {}
        try:
            state = _read_json(path)
        except (OSError, TypeError, ValueError) as exc:
            raise RuntimeError("state.json is unreadable or invalid; refusing to resume") from exc
        if not isinstance(state, dict):
            raise RuntimeError("state.json is invalid; refusing to resume")
        return state

    def _write_state(self, state: dict[str, Any]) -> None:
        self.layout.write_json_atomic("state.json", state)

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

    def _frozen_record_hashes(self) -> dict[str, str]:
        """Hash only immutable inputs/S0 artifacts; runtime outputs are mutable."""

        all_hashes = self._record_hashes()
        prefixes = ("manifests/", "s0/")
        return {relative: digest for relative, digest in all_hashes.items() if relative.startswith(prefixes)}

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
        request_records_path = self.layout.path("s0/request_records.json")
        previous_records: list[dict[str, Any]] = []
        if request_records_path.is_file():
            previous_payload = _read_json(request_records_path)
            if isinstance(previous_payload, list):
                previous_records = [copy.deepcopy(record) for record in previous_payload if isinstance(record, dict)]

        def merged_request_records(*groups: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
            merged: list[dict[str, Any]] = []
            seen: set[str] = set()
            for group in groups:
                for record in group:
                    if not isinstance(record, dict):
                        continue
                    marker = sha256(canonical(record))
                    if marker in seen:
                        continue
                    seen.add(marker)
                    merged.append(copy.deepcopy(record))
            return merged

        try:
            generated = generator.generate()
        except Exception as exc:
            client_records = getattr(self.client, "request_records", [])
            all_records = merged_request_records(
                previous_records,
                client_records if isinstance(client_records, list) else [],
            )
            self.layout.write_json("s0/request_records.json", all_records)
            self.layout.write_json(
                "s0/generation_error.json",
                {"error": str(exc), "request_count": len(all_records), "status": "s0_generation_error"},
            )
            raise
        client_records = getattr(self.client, "request_records", [])
        all_records = merged_request_records(
            previous_records,
            client_records if isinstance(client_records, list) else [],
            generated.request_records,
        )
        self.layout.write_text("s0/generation_prompt.txt", generated.generation_prompt)
        self.layout.write_json("s0/raw_response.json", generated.raw_response)
        self.layout.write_json(
            "s0/gate_packet.json",
            {"status": generated.status, "checklist": generated.gate_checklist, "feedback": generated.gate_feedback, "attempts": generated.attempts},
        )
        if generated.skill is not None:
            self.layout.write_json("s0/skill_package.json", generated.skill)
            self.layout.write_text("s0/rendered_skill.md", generated.rendered_skill or render_skill(generated.skill))
        self.layout.write_json("s0/request_records.json", all_records)
        state = {
            "pipeline_version": PIPELINE_VERSION,
            "run_dir": str(self.layout.root),
            "repo_root": str(self.repo_root.resolve()),
            "data_root": str(self.data_root.resolve()) if self.data_root is not None else None,
            "status": generated.status,
            "created_at": _now(self.clock),
            "environment_seed": self.environment_seed,
            "model_alias": self.model_alias,
            "pricing": pricing_metadata(model=self.model_alias),
            "frozen_config": {
                "repo_root": str(self.repo_root.resolve()),
                "data_root": str(self.data_root.resolve()) if self.data_root is not None else None,
                "testing_plan_size": self.testing_plan_size,
                "environment_seed": self.environment_seed,
                "model_alias": self.model_alias,
                "max_steps": 50,
                "max_episode_budget": 5 * self.testing_plan_size,
            },
            "code_fingerprint": self.code_fingerprint,
            "data_fingerprint": self.data_fingerprint,
            "s0_skill_hash": generated.skill_hash,
            "s0_gate_checklist": generated.gate_checklist,
            "s0_generation_attempts": generated.attempts,
            "s0_frozen": False,
            "manifest_hashes": {name: sha256_file(self.layout.path(f"manifests/{name}.json")) for name in MANIFEST_NAMES},
            "denylist_hash": sha256_file(self.layout.path("manifests/denylist.json")),
            "artifact_hashes": self._record_hashes(),
            "frozen_artifact_hashes": {},
            "checkpoint": {"completed": {}, "max_episode_budget": 5 * self.testing_plan_size},
            "request_records": all_records,
            "errors": [],
        }
        self._write_state(state)
        return state

    def reject_human_gate(self, checklist: dict[str, bool], *, reason: str | None = None) -> dict[str, Any]:
        """Regenerate S0 from failed public checklist labels only.

        A reviewer never edits the Skill Package.  Rejection creates a new
        generation/version and therefore a new hash before approval can be
        attempted again.
        """

        state = self._state()
        if state.get("status") != "awaiting_human_gate":
            raise RuntimeError("S0 rejection requires awaiting_human_gate state")
        if set(checklist) != set(S0_GATE_FIELDS) or any(not isinstance(value, bool) for value in checklist.values()):
            raise ValueError("human gate rejection requires exactly five boolean fields")
        failed = [field_name for field_name in S0_GATE_FIELDS if checklist[field_name] is False]
        if not failed:
            raise ValueError("reject_human_gate requires at least one false checklist field")
        attempts_used = int(state.get("s0_generation_attempts", 0))
        remaining = 3 - attempts_used
        if remaining <= 0:
            state.update({"status": "error", "errors": ["S0 human-gate regeneration limit (3) exceeded"]})
            self._write_state(state)
            return state
        if self.client is None:
            raise RuntimeError("S0 rejection requires the semantic client")
        generated = S0Generator(self.client, max_attempts=remaining).generate(feedback=failed)
        self.layout.write_text("s0/generation_prompt.txt", generated.generation_prompt)
        self.layout.write_json("s0/raw_response.json", generated.raw_response)
        self.layout.write_json(
            "s0/gate_packet.json",
            {"status": generated.status, "checklist": generated.gate_checklist, "feedback": generated.gate_feedback, "attempts": generated.attempts, "human_rejection": failed, "reason": reason},
        )
        self.layout.write_json("s0/request_records.json", generated.request_records)
        if generated.skill is None:
            state.update({"status": "error", "errors": ["S0 regeneration failed", *generated.gate_feedback], "s0_generation_attempts": attempts_used + generated.attempts})
        else:
            self.layout.write_json("s0/skill_package.json", generated.skill)
            self.layout.write_text("s0/rendered_skill.md", generated.rendered_skill or render_skill(generated.skill))
            self.layout.write_json("s0/request_records.json", generated.request_records)
            state.update({
                "status": generated.status,
                "s0_skill_hash": generated.skill_hash,
                "s0_gate_checklist": generated.gate_checklist,
                "s0_generation_attempts": attempts_used + generated.attempts,
                "s0_frozen": False,
                "request_records": generated.request_records,
                "artifact_hashes": self._record_hashes(),
            })
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
                "frozen_artifact_hashes": self._frozen_record_hashes(),
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
        frozen_hashes = state.get("frozen_artifact_hashes") or state.get("artifact_hashes", {})
        for relative, digest in frozen_hashes.items():
            path = self.layout.path(relative)
            if not path.is_file() or sha256_file(path) != digest:
                raise RuntimeError(f"frozen artifact hash mismatch: {relative}")
        return state

    def resume(self, *, continue_run: bool = False) -> dict[str, Any]:
        state = self._check_frozen(require_approved=False)
        if state.get("status") not in {"approved", "running", "error", "awaiting_human_audit"}:
            raise RuntimeError(f"resume requires approved/running/error/audit state, got {state.get('status')}")
        if state.get("status") == "awaiting_human_audit" and continue_run:
            raise RuntimeError("resume cannot bypass the pending blind human audit")
        if continue_run:
            return self.run()
        return state

    def _seed_for(self, task_id: str, condition: str, index: int) -> int:
        # A validation task is a paired unit.  The condition permutation may
        # change execution order, but must never change the environment seed
        # for baseline, structured patch, or rewrite.
        digest = hashlib.sha256(f"{self.environment_seed}|{task_id}|{index}".encode("utf-8")).hexdigest()
        return int(digest[:8], 16)

    def _episode(self, skill: dict, task_id: str, condition: str, phase: str, index: int) -> dict:
        if self.environment_factory is None:
            raise RuntimeError("environment_factory is required for episode execution")
        seed = self._seed_for(task_id, condition, index)
        env = self.environment_factory(task_id, condition, seed)
        episode_key = f"{phase}|{canonical_task_id(task_id)}|{condition}"
        trace_id = hashlib.sha256(episode_key.encode("utf-8")).hexdigest()[:24]
        runner_managed_close = False
        try:
            if self.episode_runner_factory is not None:
                row = self.episode_runner_factory(skill, env, task_id, condition)
            else:
                executor = Executor(client=self.client, skill_text=render_skill(skill), skill_hash=sha256(canonical(skill)))
                episode_runner = EpisodeRunner(env, executor, max_steps=50)
                runner_managed_close = True
                row = episode_runner.run(
                    task_id=task_id,
                    environment_seed=seed,
                    trace_id=trace_id,
                )
        finally:
            # The built-in EpisodeRunner owns close once its run has started;
            # close directly when an injected runner or pre-run construction
            # fails.
            if not runner_managed_close:
                close = getattr(env, "close", None)
                if callable(close):
                    close()
        if not isinstance(row, dict):
            raise RuntimeError("episode runner must return a dictionary")
        result = copy.deepcopy(row)
        result.setdefault("task_id", task_id)
        # Never trust an injected runner's private trace hint: support rows
        # must be tied to this actual scheduled episode.
        result["trace_id"] = trace_id
        result["condition"] = condition
        result["phase"] = phase
        result["seed"] = seed
        result.setdefault("family", classify_task_family(task_id) or "unknown")
        return result

    def _write_trajectory(self, phase: str, rows: list[dict], label: str) -> None:
        self.layout.write_jsonl(f"trajectories/{phase}/{label}.jsonl", rows)

    def _episode_key(self, phase: str, task_id: str, condition: str) -> str:
        return f"{phase}|{canonical_task_id(task_id)}|{condition}"

    def _load_checkpoint(self, state: dict[str, Any]) -> None:
        checkpoint_path = self.layout.path("checkpoint.json")
        if checkpoint_path.is_file():
            sidecar = checkpoint_path.with_name(checkpoint_path.name + ".sha256")
            if not sidecar.is_file() or sidecar.read_text(encoding="ascii").strip() != sha256_file(checkpoint_path):
                raise RuntimeError("checkpoint journal sidecar hash mismatch")
            payload = _read_json(checkpoint_path)
            if not isinstance(payload, dict) or payload.get("journal_version") != 1:
                raise RuntimeError("checkpoint journal version is invalid")
            state["checkpoint"] = copy.deepcopy(payload)
            state["checkpoint_hash"] = sha256_file(checkpoint_path)
        else:
            payload = state.get("checkpoint", {})
            if not isinstance(payload, dict):
                raise RuntimeError("checkpoint journal is missing")
            # A non-empty legacy state checkpoint without its authoritative
            # journal is ambiguous and must never be replayed.
            if payload.get("completed"):
                raise RuntimeError("checkpoint journal is missing for completed rows")
            return
        completed = payload.get("completed", {})
        if not isinstance(completed, dict):
            raise RuntimeError("checkpoint completed map is invalid")
        journal_budget = payload.get("max_episode_budget")
        if isinstance(journal_budget, bool) or not isinstance(journal_budget, int) or journal_budget <= 0:
            raise RuntimeError("checkpoint journal budget is invalid")
        frozen_budget = int(state.get("frozen_config", {}).get("max_episode_budget", journal_budget))
        if frozen_budget != journal_budget:
            raise RuntimeError("checkpoint journal budget disagrees with frozen configuration")
        max_budget = journal_budget
        if len(completed) > max_budget:
            raise RuntimeError("checkpoint exceeds frozen episode budget")
        loaded: dict[str, dict[str, Any]] = {}
        for key, entry in completed.items():
            if not isinstance(key, str) or not isinstance(entry, dict) or not isinstance(entry.get("row"), dict):
                raise RuntimeError("checkpoint row is invalid")
            row = copy.deepcopy(entry["row"])
            expected = entry.get("row_hash")
            if expected != sha256(canonical(row)):
                raise RuntimeError(f"checkpoint row hash mismatch: {key}")
            loaded[key] = row
        self._checkpoint_rows = loaded
        self._checkpoint_generation = int(payload.get("generation", 0))

    def _checkpoint_episode(self, state: dict[str, Any], key: str, row: dict[str, Any]) -> None:
        if key in self._checkpoint_rows:
            return
        max_budget = int(state.get("frozen_config", {}).get("max_episode_budget", 5 * self.testing_plan_size))
        if len(self._checkpoint_rows) >= max_budget:
            raise RuntimeError("frozen episode budget exhausted")
        value = copy.deepcopy(row)
        self._checkpoint_rows[key] = value
        previous_generation = 0
        journal_path = self.layout.path("checkpoint.json")
        if journal_path.is_file():
            previous = self._read_checkpoint_journal()
            previous_generation = int(previous.get("generation", 0))
        checkpoint = {
            "journal_version": 1,
            "generation": previous_generation + 1,
            "completed": {
                checkpoint_key: {"row": copy.deepcopy(checkpoint_row), "row_hash": sha256(canonical(checkpoint_row))}
                for checkpoint_key, checkpoint_row in sorted(self._checkpoint_rows.items())
            },
            "max_episode_budget": max_budget,
        }
        self.layout.write_json_atomic("checkpoint.json", checkpoint)
        self._checkpoint_generation = checkpoint["generation"]
        state["checkpoint"] = checkpoint
        state["checkpoint_hash"] = sha256_file(self.layout.path("checkpoint.json"))
        state["request_records"] = copy.deepcopy(self._request_records)
        self._write_state(state)

    def _read_checkpoint_journal(self) -> dict[str, Any]:
        path = self.layout.path("checkpoint.json")
        if not path.is_file():
            raise RuntimeError("checkpoint journal is missing")
        sidecar = path.with_name(path.name + ".sha256")
        if not sidecar.is_file() or sidecar.read_text(encoding="ascii").strip() != sha256_file(path):
            raise RuntimeError("checkpoint journal sidecar hash mismatch")
        payload = _read_json(path)
        if not isinstance(payload, dict) or payload.get("journal_version") != 1:
            raise RuntimeError("checkpoint journal version is invalid")
        return payload

    def _write_evolution_result(self, state: dict[str, Any], result: EvolutionResult) -> None:
        ArtifactWriter(self.layout.root).write(result)
        self.layout.write_json_atomic("ir/evolution_result.json", result)
        state["evolution_result_hash"] = sha256_file(self.layout.path("ir/evolution_result.json"))
        self._write_state(state)

    def _load_evolution_result(self, state: dict[str, Any]) -> EvolutionResult:
        path = self.layout.path("ir/evolution_result.json")
        if not path.is_file():
            raise RuntimeError("evolution result artifact is missing")
        sidecar = path.with_name(path.name + ".sha256")
        actual = sha256_file(path)
        if not sidecar.is_file() or sidecar.read_text(encoding="ascii").strip() != actual:
            raise RuntimeError("evolution result sidecar hash mismatch")
        expected = state.get("evolution_result_hash")
        if expected and expected != actual:
            raise RuntimeError("evolution result state hash mismatch")
        state["evolution_result_hash"] = actual
        return EvolutionResult.from_dict(_read_json(path))

    def _episode_from_checkpoint(
        self,
        state: dict[str, Any],
        skill: dict,
        task_id: str,
        condition: str,
        phase: str,
        index: int,
    ) -> dict[str, Any]:
        key = self._episode_key(phase, task_id, condition)
        if key in self._checkpoint_rows:
            cached = copy.deepcopy(self._checkpoint_rows[key])
            self._collect_request_records(cached)
            state["request_records"] = copy.deepcopy(self._request_records)
            self._write_state(state)
            return cached
        row = self._episode(skill, task_id, condition, phase, index)
        self._collect_request_records(row)
        self._checkpoint_episode(state, key, row)
        return row

    def _collect_request_records(self, row: Any) -> None:
        if not isinstance(row, dict):
            return
        records = row.get("request_records", [])
        if isinstance(records, list):
            for record in records:
                if not isinstance(record, dict):
                    continue
                marker = sha256(canonical(record))
                if marker not in self._request_record_keys:
                    self._request_record_keys.add(marker)
                    self._request_records.append(copy.deepcopy(record))
            consistency = self._request_consistency_error(self._request_records)
            if consistency:
                raise RuntimeError(consistency)

    def _error_state(self, state: dict[str, Any], started: str, errors: list[str], request_records: list[dict]) -> dict[str, Any]:
        ended = _now(self.clock)
        consistency = self._request_consistency_error(request_records + self._request_records)
        if consistency and consistency not in errors:
            errors.append(consistency)
        state.update({"status": "error", "ended_at": ended, "errors": list(errors), "request_records": request_records + self._request_records, "artifact_hashes": self._record_hashes()})
        self._write_code_state(started=started, ended=ended, errors=errors, request_records=request_records)
        self._write_state(state)
        return state

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
        snapshot = self._code_state_snapshot()
        state = self._state()
        skill = self._load_s0()
        records: list[dict[str, Any]] = []
        for record in list(state.get("request_records", [])) + list(request_records) + list(self._request_records):
            if isinstance(record, dict):
                records.append(copy.deepcopy(record))
        unique_records: list[dict[str, Any]] = []
        seen_records: set[str] = set()
        for record in records:
            marker = sha256(canonical(record))
            if marker not in seen_records:
                seen_records.add(marker)
                unique_records.append(record)
        dependencies: dict[str, Any] = {"python": sys.version}
        for package in ("alfworld", "textworld", "PyYAML"):
            try:
                dependencies[package] = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError:
                dependencies[package] = None
        cost = estimate_api_cost(
            unique_records,
            captured_at=(state.get("pricing") or {}).get("captured_at") if isinstance(state.get("pricing"), dict) else None,
            model=self.model_alias,
        )
        payload = {
            "git_commit": snapshot["head"],
            "dirty_worktree_diff_hash": snapshot["unstaged_diff"],
            "staged_worktree_diff_hash": snapshot["staged_diff"],
            "code_files": snapshot["files"],
            "python": sys.version,
            "dependencies": dependencies,
            "alfworld_data_version": {
                "dataset": "json_2.1.1",
                "data_root": str(self.data_root.resolve()) if self.data_root else None,
                "parsed_train_root": str(resolve_train_root(self.data_root)) if self.data_root else None,
                "manifest_hashes": state.get("manifest_hashes", {}),
                "denylist_hash": state.get("denylist_hash"),
            },
            "evaluator": "EpisodeRunner",
            "prompt_hash": sha256_file(self.layout.path("s0/generation_prompt.txt")) if self.layout.path("s0/generation_prompt.txt").exists() else None,
            "schema_hash": sha256(canonical({"schema_version": "0.1"})),
            "renderer_hash": sha256(render_skill(skill)),
            "skill_hash": sha256(canonical(skill)),
            "manifest_hashes": state.get("manifest_hashes", {}),
            "model_alias": self.model_alias,
            "observed_models": sorted({record.get("model") for record in unique_records if record.get("model")}),
            "system_fingerprints": sorted({record.get("system_fingerprint") for record in unique_records if record.get("system_fingerprint")}),
            "request_parameters": [record.get("request_body", record.get("request", {})) for record in unique_records],
            "request_records": unique_records,
            "api_cost": cost,
            "started_at": started,
            "ended_at": ended,
            "errors": list(errors),
            "retries": sum(1 for error in errors if "retry" in error.casefold()),
        }
        self.layout.write_json("code_state.json", payload)

    def _request_consistency_error(self, records: Iterable[dict[str, Any]]) -> str | None:
        values = [record for record in records if isinstance(record, dict)]
        models = {str(record.get("model")) for record in values if record.get("model")}
        fingerprints = {str(record.get("system_fingerprint")) for record in values if record.get("system_fingerprint")}
        if len(models) > 1:
            return "observed server model changed within frozen run"
        if len(fingerprints) > 1:
            return "observed system_fingerprint changed within frozen run"
        if models and next(iter(models)) != self.model_alias:
            return f"observed server model {next(iter(models))!r} differs from frozen alias {self.model_alias!r}"
        return None

    def _write_report(self, gate: dict[str, Any], metrics: dict[str, Any]) -> None:
        lines = [
            "# Stage 0 report",
            "",
            f"Go/no-go: {'GO' if gate.get('go') else 'NO-GO'}",
            "",
            "This report is exploratory and does not claim statistical significance.",
            "Privileged ALFWorld expert-plan evidence: deferred (not read from public episode artifacts).",
            "",
            "## Gate conditions",
            "",
        ]
        for key, value in gate.get("conditions", {}).items():
            lines.append(f"- {key}: {'PASS' if value else 'FAIL'}")
        lines.extend(["", "## Metrics", "", "```json", json.dumps(_plain(metrics), ensure_ascii=False, indent=2, sort_keys=True), "```", ""])
        self.layout.write_text("report/stage0_report.md", "\n".join(lines))

    def _write_audit_packet(self, evolution: EvolutionResult | None, current_skill: dict | None = None) -> str:
        if evolution is None:
            packet = {
                "audit_status": "awaiting_human_audit",
                "reason": "no_evolution",
                "candidates": [],
                "dynamic_results_hidden": True,
                "expert_plan_included": False,
                "expert_plan_status": "deferred_unavailable_in_public_trajectory_artifacts",
            }
        else:
            entries = [
                ("structured_patch", evolution.structured_candidate),
                ("full_rewrite", evolution.rewrite_candidate),
            ]
            # Blind order is frozen per run but is not representation order.
            blind_seed = int(sha256(f"{self.environment_seed}|{sha256(canonical(current_skill or {}))}" )[:8], 16)
            random.Random(blind_seed).shuffle(entries)
            candidates = []
            private_mapping: dict[str, str] = {}
            evidence_refs = [
                {"trace_id": ref.get("trace_id"), "trajectory_steps": copy.deepcopy(ref.get("trajectory_steps", []))}
                for ref in evolution.root_cause.get("supported_by", [])
                if isinstance(ref, dict)
            ]
            for candidate_method, candidate in entries:
                if candidate is None:
                    continue
                candidate_id = f"candidate_{len(candidates) + 1}"
                private_mapping[candidate_id] = candidate_method
                structural = candidate.structural_result if isinstance(candidate.structural_result, dict) else {}
                final_skill = structural.get("skill") if isinstance(structural.get("skill"), dict) else current_skill
                if not isinstance(final_skill, dict):
                    final_skill = {"skill_package": {}}
                candidates.append(
                    {
                        "candidate_id": candidate_id,
                        "final_skill_package": copy.deepcopy(final_skill.get("skill_package", {})),
                        "semantic_changes": diff_skill(current_skill, final_skill) if isinstance(current_skill, dict) and "skill_package" in final_skill else [],
                        "evidence_refs": copy.deepcopy(evidence_refs),
                        "candidate_semantics": {"root_cause_id": evolution.root_cause.get("root_cause_id")},
                    }
                )
            self.layout.write_json("audit/private_candidate_mapping.json", private_mapping)
            packet = {
                "audit_status": "awaiting_human_audit",
                "auditor_count": 0,
                "rubric_version": "stage0-8-item",
                "failures": evolution.failures,
                "preservations": evolution.preservations,
                "root_cause": evolution.root_cause,
                "candidates": candidates,
                "dynamic_results_hidden": True,
                "provenance_hidden": True,
                "expert_plan_included": False,
                "expert_plan_status": "deferred_unavailable_in_public_trajectory_artifacts",
            }
        self.layout.write_json("audit/blinded_packet.json", packet)
        return sha256_file(self.layout.path("audit/blinded_packet.json"))

    def submit_human_scores(self, scores: dict[str, Any] | str | Path) -> dict[str, Any]:
        """Validate the external blind-audit packet and unlock completion."""

        state = self._state()
        if state.get("status") != "awaiting_human_audit":
            raise RuntimeError("human scores require awaiting_human_audit state")
        if isinstance(scores, (str, Path)):
            payload = _read_json(Path(scores))
        else:
            payload = copy.deepcopy(scores)
        if not isinstance(payload, dict):
            raise ValueError("human scores must be a JSON object")
        raw_reviewers = payload.get("reviewers")
        if raw_reviewers is None:
            raw_reviewers = [payload]
        if not isinstance(raw_reviewers, list) or not raw_reviewers:
            raise ValueError("human scores require at least one reviewer")
        reviewers: list[dict[str, Any]] = []
        forbidden_text = json.dumps(payload, ensure_ascii=False, sort_keys=True).casefold()
        if any(token in forbidden_text for token in ("condition", "baseline", "structured_patch", "full_rewrite", "validation_score")):
            raise ValueError("human scores must remain blind to condition mapping and validation scores")
        packet = _read_json(self.layout.path("audit/blinded_packet.json")) if self.layout.path("audit/blinded_packet.json").is_file() else {}
        expected_packet_hash = state.get("audit_packet_hash")
        actual_packet_hash = sha256_file(self.layout.path("audit/blinded_packet.json")) if self.layout.path("audit/blinded_packet.json").is_file() else None
        if expected_packet_hash and expected_packet_hash != actual_packet_hash:
            raise RuntimeError("blinded audit packet hash mismatch")
        candidate_ids = [
            str(candidate.get("candidate_id"))
            for candidate in packet.get("candidates", [])
            if isinstance(candidate, dict) and isinstance(candidate.get("candidate_id"), str)
        ]
        if not candidate_ids:
            candidate_ids = ["no_candidate"]
        for index, reviewer in enumerate(raw_reviewers):
            if not isinstance(reviewer, dict):
                raise ValueError("reviewer entry must be an object")
            score_map = reviewer.get("scores", reviewer)
            if not isinstance(score_map, dict):
                raise ValueError("reviewer scores must be an object")
            # Each anonymous candidate receives an independent complete
            # eight-item rubric.  For a single/no candidate, accept the
            # compact direct eight-field form as a convenience.
            if set(score_map) == set(AUDIT_RUBRIC_FIELDS):
                if len(candidate_ids) != 1:
                    raise ValueError("scores must be provided separately for every anonymous candidate")
                candidate_score_maps = {candidate_ids[0]: score_map}
            else:
                if set(score_map) != set(candidate_ids):
                    raise ValueError("human scores must cover every anonymous candidate exactly once")
                candidate_score_maps = score_map
            normalized: dict[str, dict[str, float]] = {}
            for candidate_id in candidate_ids:
                candidate_score = candidate_score_maps[candidate_id]
                if not isinstance(candidate_score, dict) or set(candidate_score) != set(AUDIT_RUBRIC_FIELDS):
                    raise ValueError("human scores must include all eight rubric fields for each candidate")
                normalized[candidate_id] = {}
                for field_name in AUDIT_RUBRIC_FIELDS:
                    value = candidate_score[field_name]
                    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 1 <= float(value) <= 5:
                        raise ValueError(f"invalid human score for {candidate_id}.{field_name}")
                    normalized[candidate_id][field_name] = float(value)
            reviewers.append({
                "reviewer_id": str(reviewer.get("reviewer_id", reviewer.get("reviewer", f"reviewer_{index + 1}"))),
                "scores": normalized,
            })
        normalized_payload = {"reviewers": reviewers, "rubric_version": "stage0-8-item"}
        self.layout.write_json("audit/human_scores.json", normalized_payload)
        metrics_path = self.layout.path("report/metrics.json")
        if metrics_path.is_file():
            metrics = _read_json(metrics_path)
            if isinstance(metrics, dict):
                metrics["human_audit"] = copy.deepcopy(normalized_payload)
                self.layout.write_json("report/metrics.json", metrics)
                self._write_report(state.get("stage0_gate", {}), metrics)
        packet_path = self.layout.path("audit/blinded_packet.json")
        if packet_path.is_file():
            packet = _read_json(packet_path)
            if isinstance(packet, dict):
                packet["audit_status"] = "complete"
                packet["auditor_count"] = len(reviewers)
                self.layout.write_json("audit/blinded_packet.json", packet)
        metrics_after_audit = _read_json(metrics_path) if metrics_path.is_file() else {}
        cost_status = ((metrics_after_audit.get("api_cost") or {}).get("status") if isinstance(metrics_after_audit, dict) else None) or state.get("cost_status", "incomplete")
        state["human_audit"] = {
            "status": "complete",
            "reviewer_count": len(reviewers),
            "audit_status": "exploratory_single_audit" if len(reviewers) == 1 else "two_reviewer_audit",
            "expert_plan_status": packet.get("expert_plan_status", "deferred_unavailable_in_public_trajectory_artifacts"),
            "scores_hash": sha256_file(self.layout.path("audit/human_scores.json")),
        }
        state["cost_status"] = cost_status
        if cost_status != "complete":
            state["status"] = "awaiting_human_audit"
            state["completion_scope"] = "blocked_cost_incomplete"
            state["artifact_hashes"] = self._record_hashes()
            self._write_state(state)
            return state
        state["status"] = "completed"
        state["completion_scope"] = "stage0_metrics_with_expert_plan_deferred"
        state["completed_at"] = _now(self.clock)
        state["artifact_hashes"] = self._record_hashes()
        self._write_state(state)
        return state

    def run(self) -> dict[str, Any]:
        state = self._check_frozen(require_approved=False)
        if state.get("status") not in {"approved", "running", "error"}:
            raise RuntimeError(f"run requires approved/running/error state, got {state.get('status')}")
        started = _now(self.clock)
        errors: list[str] = []
        request_records: list[dict] = []
        saved_records = state.get("request_records", [])
        if isinstance(saved_records, list):
            request_records.extend(record for record in saved_records if isinstance(record, dict))
        s0_records_path = self.layout.path("s0/request_records.json")
        if s0_records_path.exists():
            loaded_s0_records = _read_json(s0_records_path)
            if isinstance(loaded_s0_records, list):
                request_records.extend(record for record in loaded_s0_records if isinstance(record, dict))
        self._request_records = copy.deepcopy(request_records)
        self._request_record_keys = {sha256(canonical(record)) for record in self._request_records if isinstance(record, dict)}
        manifests = {name: _read_json(self.layout.path(f"manifests/{name}.json"))["task_ids"] for name in MANIFEST_NAMES}
        s0 = self._load_s0()
        self._load_checkpoint(state)
        state["status"] = "running"
        state["started_at"] = started
        self._write_state(state)
        calibration_rows: list[dict] = []
        try:
            for index, task_id in enumerate(manifests["calibration"]):
                calibration_rows.append(self._episode_from_checkpoint(state, s0, task_id, "baseline", "calibration", index))
        except Exception as exc:
            errors.append(repr(exc))
            self._write_trajectory("calibration", calibration_rows, "episodes")
            return self._error_state(state, started, errors, request_records)
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
                evolution_rows.append(self._episode_from_checkpoint(state, s0, task_id, "baseline", "evolution", index))
        except Exception as exc:
            errors.append(repr(exc))
            self._write_trajectory("evolution", evolution_rows, "episodes")
            return self._error_state(state, started, errors, request_records)
        self._write_trajectory("evolution", evolution_rows, "episodes")
        evolution_result: EvolutionResult | None = None
        frozen_evolution_path = self.layout.path("ir/evolution_result.json")
        try:
            if frozen_evolution_path.is_file():
                evolution_result = self._load_evolution_result(state)
                request_records.extend(evolution_result.request_records)
                self._collect_request_records({"request_records": evolution_result.request_records})
            else:
                evolution_result = EvolutionEngine(self.client).run(evolution_rows, s0)
                self._write_evolution_result(state, evolution_result)
                request_records.extend(evolution_result.request_records)
                self._collect_request_records({"request_records": evolution_result.request_records})
            consistency = self._request_consistency_error(self._request_records)
            if consistency:
                raise RuntimeError(consistency)
        except Exception as exc:
            errors.append(repr(exc))
            return self._error_state(state, started, errors, request_records)
        state["audit_packet_hash"] = self._write_audit_packet(evolution_result, s0)
        self._write_state(state)

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
                    skipped = {"task_id": item["task_id"], "condition": condition, "skipped": True, "reason": "candidate_not_valid"}
                    validation[condition].append(skipped)
                    self._checkpoint_episode(state, self._episode_key("validation", item["task_id"], condition), skipped)
                    continue
                try:
                    validation[condition].append(self._episode_from_checkpoint(state, skill, item["task_id"], condition, "validation", task_index))
                except Exception as exc:
                    errors.append(repr(exc))
                    return self._error_state(state, started, errors, request_records)
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
        api_cost = estimate_api_cost(
            request_records + self._request_records,
            captured_at=(state.get("pricing") or {}).get("captured_at") if isinstance(state.get("pricing"), dict) else None,
            model=self.model_alias,
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
            "api_cost": api_cost,
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
        consistency_error = self._request_consistency_error(request_records + self._request_records)
        if consistency_error:
            errors.append(consistency_error)
            return self._error_state(state, started, errors, request_records)
        self._write_code_state(started=started, ended=ended, errors=errors, request_records=request_records)
        state.update({"status": "awaiting_human_audit", "ended_at": ended, "calibration_gate": calibration_gate, "stage0_gate": gate, "pending_metrics": True, "cost_status": api_cost["status"], "errors": errors, "artifact_hashes": self._record_hashes(), "request_records": request_records + self._request_records})
        self._write_state(state)
        return state


__all__ = ["AUDIT_RUBRIC_FIELDS", "Stage0ArtifactLayout", "Stage0Pipeline"]
