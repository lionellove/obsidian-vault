"""Train-only Stage 0 preflight runner.

This repository contains offline IR/evolution seams but no formal rollout/API
or dynamic-validation orchestration. Consequently ``--dry-run`` emits
explicitly marked scaffold artifacts and every non-dry
invocation exits non-zero before claiming that Stage 0 was prepared or run.
"""
from __future__ import annotations

import argparse
import itertools
import json
import random
import re
import sys
import time
from pathlib import Path
from typing import Any, Iterable

from stage0_core import (
    FAMILIES,
    TASK_PREFIXES,
    canonical_task_id,
    classify_task_family,
    render_skill,
    sha256,
    sha256_file,
    task_group_key,
    task_id_key,
    validate_skill,
)
from stage0_metrics import pricing_metadata

SAMPLE_SEED = 20260825
ENVIRONMENT_SEED = 20260825
FORBIDDEN_SPLITS = {"valid_seen", "valid_unseen", "valid_train", "test", "dev", "validation"}
CONDITIONS = ("baseline", "structured_patch", "full_rewrite")


def resolve_train_root(data_root: str | Path) -> Path:
    """Accept only a json_2.1.1 root (using its train child) or terminal train."""

    requested = Path(data_root)
    root = requested.resolve(strict=False)
    parts = [part.casefold() for part in (*requested.parts, *root.parts)]
    if any(part in FORBIDDEN_SPLITS for part in parts):
        raise ValueError("data root contains a forbidden split; Stage 0 accepts train only")
    name = requested.name.casefold()
    if name not in {"train", "json_2.1.1", "valid_train"}:
        name = root.name.casefold()
    if name == "train":
        if not root.is_dir():
            raise ValueError(f"train data root is not a directory: {root}")
        return root
    if name == "valid_train":
        raise ValueError("valid_train is not the Stage 0 train split; use train")
    if name == "json_2.1.1":
        children = [child for child in root.iterdir()] if root.is_dir() else []
        train = next((child for child in children if child.name.casefold() == "train"), None)
        if train is None or not train.is_dir():
            raise ValueError("json_2.1.1 root must contain a train directory")
        return train.resolve(strict=False)
    raise ValueError("data root must be a terminal train directory or json_2.1.1 root")


def json_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.json")) if root.exists() else []


def _looks_like_task_id(value: Any) -> bool:
    """Recognize an ALFWorld game path while rejecting arbitrary noise."""

    if not isinstance(value, str):
        return False
    normalized = value.strip().replace("\\", "/")
    lowered = normalized.casefold()
    return (
        lowered.endswith("game.tw-pddl")
        and "trial_" in lowered
        and classify_task_family(normalized) is not None
    )


def _nested_task_ids(value: Any) -> Iterable[str]:
    """Recursively discover task paths in any JSON shape.

    Historical artifacts use exact ``task_id``/``task_ids`` keys, but some
    result batches use a top-level string array or a ``gamefile`` field.  A
    final path-shape check keeps unrelated strings such as ``not-a-task`` out
    of the denylist.
    """

    if isinstance(value, dict):
        for key, child in value.items():
            # Exact task fields remain supported; recursive traversal also
            # catches gamefile and top-level/batched path values.
            if key.casefold() in {"task_id", "task_ids", "gamefile", "game_file"}:
                yield from _nested_task_ids(child)
            yield from _nested_task_ids(child)
    elif isinstance(value, list):
        for child in value:
            yield from _nested_task_ids(child)
    elif _looks_like_task_id(value):
        yield value


def existing_task_keys(repo: Path, train_root: str | Path | None = None) -> set[str]:
    """Find historical IDs recursively and return exact canonical comparison keys."""

    found: set[str] = set()
    for path in json_files(repo / "results") + json_files(repo / "configs"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        for value in _nested_task_ids(payload):
            try:
                found.add(task_id_key(value, train_root=train_root))
            except ValueError:
                continue
    return found


def _candidate_paths(train_root: Path) -> dict[str, list[Path]]:
    candidates = {family: [] for family in FAMILIES}
    for game in sorted(train_root.rglob("game.tw-pddl")):
        relative_parts = [part.casefold() for part in game.relative_to(train_root).parts]
        if any(part in FORBIDDEN_SPLITS for part in relative_parts):
            raise ValueError(f"forbidden split nested under train root: {game}")
        family = classify_task_family(game)
        if family is not None:
            candidates[family].append(game)
    return candidates


def _assert_split_disjoint(chosen: dict[str, list[str]]) -> None:
    ids = {name: {task_id_key(value) for value in values} for name, values in chosen.items()}
    groups = {name: {task_group_key(value) for value in values} for name, values in chosen.items()}
    names = tuple(chosen)
    for index, left in enumerate(names):
        for right in names[index + 1 :]:
            if ids[left] & ids[right]:
                raise RuntimeError(f"task ID overlap between {left} and {right}")
            if groups[left] & groups[right]:
                raise RuntimeError(f"task group overlap between {left} and {right}")


def sample(data_root: Path, deny: set[str], seed: int = SAMPLE_SEED) -> dict[str, list[str]]:
    """Sample 9 groups/family from train and return canonical relative IDs."""

    train_root = resolve_train_root(data_root)
    deny_keys = {task_id_key(value) for value in deny}
    candidates = _candidate_paths(train_root)
    chosen = {"calibration": [], "evolution": [], "patch_validation": []}
    rng = random.Random(seed)
    for family in sorted(FAMILIES):
        by_group: dict[str, tuple[str, Path]] = {}
        for path in candidates[family]:
            task_id = canonical_task_id(path, train_root=train_root)
            if task_id_key(task_id) in deny_keys:
                continue
            group = task_group_key(path)
            # One representative per near-duplicate group.  Sorting by the
            # canonical ID makes the choice independent of absolute roots.
            previous = by_group.get(group)
            if previous is None or task_id.casefold() < previous[0].casefold():
                by_group[group] = (task_id, path)
        pool = sorted((task_id for task_id, _ in by_group.values()), key=str.casefold)
        if len(pool) < 9:
            raise RuntimeError(f"{family}: need 9 unique task groups, found {len(pool)}")
        rng.shuffle(pool)
        for index, task_id in enumerate(pool[:9]):
            split = ("calibration", "evolution", "patch_validation")[index // 3]
            chosen[split].append(task_id)
    for values in chosen.values():
        values.sort(key=str.casefold)
    _assert_split_disjoint(chosen)
    return chosen


def balanced_validation_conditions(task_ids: list[str], seed: int = SAMPLE_SEED) -> list[dict[str, Any]]:
    """Assign all six condition permutations exactly three times to 18 tasks."""

    if not isinstance(task_ids, list) or len(task_ids) != 18:
        raise ValueError("balanced validation requires exactly 18 task IDs")
    canonical_ids = [canonical_task_id(value) for value in task_ids]
    keys = [task_id_key(value) for value in canonical_ids]
    if len(set(keys)) != len(keys):
        raise ValueError("validation task IDs must be unique")
    orders = list(itertools.permutations(CONDITIONS))
    schedule_orders = [order for order in orders for _ in range(3)]
    rng = random.Random(seed)
    rng.shuffle(canonical_ids)
    rng.shuffle(schedule_orders)
    return [
        {"task_id": task_id, "condition_order": list(order)}
        for task_id, order in zip(canonical_ids, schedule_orders)
    ]


# Short alias for callers/tests that use the plan's wording.
validation_conditions = balanced_validation_conditions


def baseline_skill() -> dict:
    """Return a visibly non-production placeholder used only by dry-run."""

    nodes = [
        {"id": "parse_goal", "type": "decision", "instruction": "Parse the goal and required object state.", "scope": {"level": "global"}},
        {"id": "search_target", "type": "action", "instruction": "Explore with admissible actions until the target is established.", "scope": {"level": "global"}},
        {"id": "transform_object", "type": "action", "instruction": "Apply the required transformation to the target.", "scope": {"level": "global"}},
        {"id": "place_object", "type": "action", "instruction": "Place the target in the required receptacle.", "scope": {"level": "global"}},
        {"id": "verify_goal", "type": "verification", "instruction": "Verify the goal state.", "scope": {"level": "global"}},
        {"id": "finish", "type": "terminal", "instruction": "Finish only after verification.", "scope": {"level": "global"}},
    ]
    edges = [
        {"id": f"e{index}", "source": source, "target": target, "condition": condition}
        for index, (source, target, condition) in enumerate(
            [
                ("parse_goal", "search_target", "target location not established"),
                ("search_target", "transform_object", "target acquired"),
                ("transform_object", "place_object", "required state established"),
                ("place_object", "verify_goal", "placed"),
                ("verify_goal", "finish", "goal established"),
            ],
            1,
        )
    ]
    return {
        "skill_package": {
            "schema_version": "0.1",
            "package_id": "alfworld-stage0-s0-placeholder",
            "entry_node": "parse_goal",
            "nodes": nodes,
            "edges": edges,
            "constraints": [],
            "verifications": [],
            "fallbacks": [],
        }
    }


def _write_json(path: Path, payload: Any) -> str:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return sha256_file(path)


def _write_preregistration(out: Path, payload: dict[str, Any]) -> str:
    """Write final JSON once, then hash those exact bytes in a sidecar."""

    path = out / "preregistration.json"
    _write_json(path, payload)
    digest = sha256_file(path)
    (out / "preregistration.sha256").write_text(digest + "\n", encoding="ascii")
    return digest


def _prepare_denylist(repo_root: Path, manifests_dir: Path, train_root: Path | None) -> tuple[set[str], str]:
    deny = existing_task_keys(repo_root, train_root=train_root)
    deny_path = manifests_dir / "denylist.json"
    _write_json(deny_path, sorted(deny))
    deny_hash = sha256_file(deny_path)
    (manifests_dir / "denylist.sha256").write_text(deny_hash + "\n", encoding="ascii")
    return deny, deny_hash


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--s0-file", type=Path, default=None, help="human-gated S0 input (execution remains unavailable)")
    args = parser.parse_args(argv)

    run_id = args.run_id or time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out = args.repo_root / "results" / "skillgraph_stage0" / run_id
    manifests_dir = out / "manifests"
    s0_dir = out / "s0"
    manifests_dir.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any] = {
        "run_id": run_id,
            "status": "scaffold_placeholder" if args.dry_run else "blocked_prerequisites",
        "artifact_status": "scaffold_placeholder" if args.dry_run else "blocked",
        "not_experiment_artifact": bool(args.dry_run),
        "sample_seed": SAMPLE_SEED,
        "environment_seed": ENVIRONMENT_SEED,
        "data_root": str(args.data_root),
        "model": "deepseek-v4-flash",
        "pricing": pricing_metadata(model="deepseek-v4-flash"),
        "max_steps": 50,
        "env_type": "AlfredTWEnv",
        "domain_randomization": False,
        "execution": {
            "rollout": "available_via_stage0_cli_after_live_confirmation",
            "api": "available_via_stage0_cli_after_live_confirmation",
            "ir_pipeline": "implemented_offline_in_stage0_pipeline",
            "three_layer_validation": "implemented_offline_in_stage0_pipeline",
        },
    }

    train_root: Path | None = None
    try:
        train_root = resolve_train_root(args.data_root)
        payload["train_root"] = str(train_root)
    except (OSError, ValueError) as exc:
        payload["sampling_status"] = "blocked_data_root"
        payload["sampling_error"] = str(exc)
    deny, deny_hash = _prepare_denylist(args.repo_root, manifests_dir, train_root)
    payload["denylist_count"] = len(deny)
    payload["denylist_hash"] = deny_hash

    if not args.dry_run:
        if args.s0_file is None:
            payload["error"] = (
                "formal run blocked: provide --s0-file and use stage0_cli run with explicit live confirmation"
            )
        elif not args.s0_file.is_file():
            payload["error"] = f"non-dry-run is disabled and --s0-file does not exist: {args.s0_file}"
        else:
            payload["s0_file"] = str(args.s0_file)
            payload["error"] = "formal run blocked: stage0_cli requires explicit live confirmation and environment configuration"
        _write_preregistration(out, payload)
        print(json.dumps({"run_dir": str(out), "status": payload["status"], "error": payload["error"]}, ensure_ascii=False))
        return 2

    if train_root is not None:
        try:
            manifests = sample(train_root, deny, seed=SAMPLE_SEED)
            payload["sampling_status"] = "scaffold_sampled"
            payload["manifest_hashes"] = {}
            for name, task_ids in manifests.items():
                manifest = {
                    "artifact_status": "scaffold_placeholder",
                    "count": len(task_ids),
                    "sample_seed": SAMPLE_SEED,
                    "task_ids": task_ids,
                    "group_keys": [task_group_key(task_id) for task_id in task_ids],
                }
                path = manifests_dir / f"{name}.json"
                payload["manifest_hashes"][name] = _write_json(path, manifest)
            validation = balanced_validation_conditions(manifests["patch_validation"], seed=SAMPLE_SEED)
            payload["validation_conditions_hash"] = _write_json(
                manifests_dir / "validation_conditions.json",
                {"artifact_status": "scaffold_placeholder", "conditions": validation},
            )
        except (OSError, RuntimeError, ValueError) as exc:
            payload["sampling_status"] = "blocked_sampling"
            payload["sampling_error"] = str(exc)

    s0 = baseline_skill()
    errors = validate_skill(s0, enforce_budget=True)
    if errors:
        payload["s0_status"] = "invalid_placeholder"
        payload["s0_errors"] = errors
    else:
        s0_dir.mkdir(parents=True, exist_ok=True)
        package_path = s0_dir / "skill_package.json"
        rendered_path = s0_dir / "rendered_skill.md"
        payload["s0_status"] = "scaffold_placeholder_not_human_gated"
        payload["s0_hash"] = _write_json(package_path, s0)
        rendered_path.write_text(render_skill(s0), encoding="utf-8")
        payload["rendered_hash"] = sha256_file(rendered_path)
        payload["rendered_hash_is_utf8_file_sha256"] = True
        _write_json(
            s0_dir / "metadata.json",
            {"artifact_status": "scaffold_placeholder", "human_gate": "not_run", "production_use": False},
        )

    _write_preregistration(out, payload)
    print(
        json.dumps(
            {
                "run_dir": str(out),
                "status": payload["status"],
                "denylist_count": len(deny),
                "denylist_hash": payload["denylist_hash"],
                "s0_hash": payload.get("s0_hash"),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
