"""CLI lifecycle for the paused Stage 0 pipeline."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from stage0_core import canonical, sha256
from stage0_llm import DeepSeekClient
from stage0_pipeline import MANIFEST_NAMES, Stage0Pipeline
from stage0_run import ENVIRONMENT_SEED, resolve_train_root
from stage0_s0 import S0_GATE_FIELDS


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _task_manifests(run_dir: Path) -> dict[str, list[str]]:
    return {name: _read_json(run_dir / "manifests" / f"{name}.json")["task_ids"] for name in MANIFEST_NAMES}


def _denylist(run_dir: Path) -> set[str]:
    payload = _read_json(run_dir / "manifests" / "denylist.json")
    return set(payload.get("task_ids", [])) if isinstance(payload, dict) else set(payload)


def _build_pipeline(args: argparse.Namespace, *, client: Any) -> Stage0Pipeline:
    run_dir = Path(args.run_dir)
    state = _read_json(run_dir / "state.json") if (run_dir / "state.json").exists() else {}
    saved_repo = state.get("repo_root") or state.get("frozen_config", {}).get("repo_root")
    saved_data = state.get("data_root") or state.get("frozen_config", {}).get("data_root")
    explicit_repo = getattr(args, "repo_root", None)
    explicit_data = getattr(args, "data_root", None)
    if saved_repo and explicit_repo and Path(explicit_repo).resolve() != Path(saved_repo).resolve():
        raise RuntimeError("--repo-root disagrees with frozen state repo_root")
    if saved_data and explicit_data:
        try:
            saved_train = resolve_train_root(saved_data)
            explicit_train = resolve_train_root(explicit_data)
            if saved_train.resolve() != explicit_train.resolve():
                raise RuntimeError("--data-root disagrees with frozen state data_root")
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"--data-root cannot be reconciled with frozen state: {exc}") from exc
    repo_root = Path(saved_repo or explicit_repo) if (saved_repo or explicit_repo) else None
    data_root = Path(saved_data or explicit_data) if (saved_data or explicit_data) else None
    if state and repo_root is None:
        raise RuntimeError("frozen state is missing repo_root")
    manifests = _task_manifests(run_dir) if (run_dir / "manifests").exists() else None
    denylist = _denylist(run_dir) if (run_dir / "manifests" / "denylist.json").exists() else None
    data_fingerprint = state.get("data_fingerprint") if state else None
    environment_factory = None
    if data_root is not None:
        from stage0_alfworld import create_alfworld_env

        train_root = resolve_train_root(data_root)
        environment_factory = lambda task_id, condition, seed: create_alfworld_env(train_root, task_id, environment_seed=seed)
    frozen = state.get("frozen_config", {}) if isinstance(state.get("frozen_config"), dict) else {}
    return Stage0Pipeline(
        run_dir,
        client=client,
        environment_factory=environment_factory,
        repo_root=repo_root,
        data_root=data_root,
        task_manifests=manifests,
        denylist=denylist,
        environment_seed=state.get("environment_seed", ENVIRONMENT_SEED),
        testing_plan_size=int(frozen.get("testing_plan_size", state.get("testing_plan_size", 18))),
        # Recompute the current code fingerprint; passing the frozen value
        # here would make resume unable to detect a dirty/code change.
        code_fingerprint=None,
        data_fingerprint=data_fingerprint,
        model_alias=state.get("model_alias", "deepseek-v4-flash"),
    )


class _OfflineS0Client:
    def complete_meta(self, role, context, token_budget):
        from stage0_run import baseline_skill

        if role == "s0_generator":
            return json.dumps(baseline_skill())
        return json.dumps({"root_causes": []})


def _offline_smoke(run_dir: Path) -> int:
    manifests = {
        "calibration": ["pick_and_place_simple-a-m-r-1/trial_c/game.tw-pddl", "clean_and_place-a-m-r-2/trial_c/game.tw-pddl", "heat_and_place-a-m-r-3/trial_c/game.tw-pddl"],
        "evolution": ["cool_and_place-a-m-r-4/trial_e/game.tw-pddl", "pick_two_obj_and_place-a-m-r-5/trial_e/game.tw-pddl", "look_at_obj_in_light-a-m-r-6/trial_e/game.tw-pddl"],
        "patch_validation": ["pick_and_place_simple-b-m-r-7/trial_v/game.tw-pddl", "clean_and_place-b-m-r-8/trial_v/game.tw-pddl", "heat_and_place-b-m-r-9/trial_v/game.tw-pddl"],
    }
    pipeline = Stage0Pipeline(run_dir, client=_OfflineS0Client(), task_manifests=manifests, testing_plan_size=3)
    state = pipeline.prepare()
    if state.get("status") != "awaiting_human_gate":
        print(json.dumps(state, ensure_ascii=False))
        return 2
    pipeline.approve({field_name: True for field_name in S0_GATE_FIELDS}, auditor="offline-scaffold", timestamp="offline")
    state = pipeline.status()
    state["status"] = "offline_smoke"
    state["artifact_status"] = "scaffold_placeholder"
    state["not_experiment_artifact"] = True
    pipeline._write_state(state)
    pipeline.layout.write_text("report/stage0_report.md", "# Stage 0 offline smoke\n\nStatus: scaffold_placeholder\n\nNo API request or episode was executed.\n")
    print(json.dumps({"run_dir": str(run_dir), "status": "offline_smoke", "artifact_status": "scaffold_placeholder"}, ensure_ascii=False))
    return 0


def _require_live(args: argparse.Namespace, *, require_confirmation: bool) -> str | None:
    if require_confirmation and not getattr(args, "confirm_live_run", False):
        return "live run requires --confirm-live-run"
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        return "live run requires DEEPSEEK_API_KEY"
    state_path = Path(args.run_dir) / "state.json"
    saved_data = None
    if state_path.is_file():
        try:
            state = _read_json(state_path)
            saved_data = state.get("data_root") or state.get("frozen_config", {}).get("data_root")
        except (OSError, ValueError, TypeError):
            saved_data = None
    data_root = getattr(args, "data_root", None) or saved_data
    if not data_root:
        return "live run requires --data-root"
    try:
        resolve_train_root(data_root)
    except (OSError, ValueError) as exc:
        return f"live run requires a valid train data root: {exc}"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stage0_cli")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--run-dir", required=True, type=Path)
    prepare.add_argument("--repo-root", type=Path, default=None)
    prepare.add_argument("--data-root", required=True, type=Path)
    approve = sub.add_parser("approve")
    approve.add_argument("--run-dir", required=True, type=Path)
    approve.add_argument("--checklist", required=True, type=Path)
    approve.add_argument("--auditor", required=True)
    approve.add_argument("--timestamp", default=None)
    reject = sub.add_parser("reject-s0")
    reject.add_argument("--run-dir", required=True, type=Path)
    reject.add_argument("--checklist", required=True, type=Path)
    reject.add_argument("--reason", default=None)
    reject.add_argument("--repo-root", type=Path, default=None)
    reject.add_argument("--data-root", type=Path, default=None)
    for name in ("submit-audit", "audit-submit"):
        audit = sub.add_parser(name)
        audit.add_argument("--run-dir", required=True, type=Path)
        audit.add_argument("--scores", required=True, type=Path)
    status = sub.add_parser("status")
    status.add_argument("--run-dir", required=True, type=Path)
    for command in ("run", "resume"):
        item = sub.add_parser(command)
        item.add_argument("--run-dir", required=True, type=Path)
        item.add_argument("--repo-root", type=Path, default=None)
        item.add_argument("--data-root", type=Path, default=None)
        item.add_argument("--confirm-live-run", action="store_true")
    offline = sub.add_parser("offline-smoke")
    offline.add_argument("--run-dir", required=True, type=Path)
    args = parser.parse_args(argv)

    try:
        if args.command == "offline-smoke":
            return _offline_smoke(args.run_dir)
        if args.command == "status":
            path = args.run_dir / "state.json"
            print(path.read_text(encoding="utf-8") if path.exists() else json.dumps({"status": "missing"}))
            return 0
        if args.command == "approve":
            checklist = _read_json(args.checklist)
            pipeline = _build_pipeline(args, client=None)
            state = pipeline.approve(checklist, auditor=args.auditor, timestamp=args.timestamp)
            print(json.dumps({"status": state["status"], "run_dir": str(args.run_dir)}, ensure_ascii=False))
            return 0
        if args.command == "reject-s0":
            error = _require_live(args, require_confirmation=False)
            if error:
                print(error, file=sys.stderr)
                return 2
            checklist = _read_json(args.checklist)
            pipeline = _build_pipeline(args, client=DeepSeekClient())
            state = pipeline.reject_human_gate(checklist, reason=args.reason)
            print(json.dumps({"status": state["status"], "run_dir": str(args.run_dir)}, ensure_ascii=False))
            return 0 if state.get("status") != "error" else 2
        if args.command in {"submit-audit", "audit-submit"}:
            pipeline = _build_pipeline(args, client=None)
            state = pipeline.submit_human_scores(args.scores)
            print(json.dumps({"status": state["status"], "run_dir": str(args.run_dir)}, ensure_ascii=False))
            return 0
        error = _require_live(args, require_confirmation=args.command in {"run", "resume"})
        if error:
            print(error, file=sys.stderr)
            return 2
        client = DeepSeekClient()
        pipeline = _build_pipeline(args, client=client)
        state = pipeline.prepare() if args.command == "prepare" else pipeline.resume(continue_run=True)
        print(json.dumps({"status": state.get("status"), "run_dir": str(args.run_dir)}, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(f"stage0_cli blocked: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
