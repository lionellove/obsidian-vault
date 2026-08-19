"""Run fixed-task ALFWorld conditions with identical evaluator settings."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from experiment_common import ROOT, write_json


SKILL_FOR_CONDITION = {
    "student_baseline": None,
    "student_self_skill": "skills/student_self_skill.md",
    "student_teacher_skill": "skills/teacher_skill.md",
    "student_irrelevant_skill": "skills/irrelevant_skill.md",
    "student_shuffled_skill": "skills/shuffled_teacher_skill.md",
}


def run_condition(condition: str, model: str, task_file: Path, output_root: Path, max_steps: int) -> dict:
    env = os.environ.copy()
    env.update({
        "MODEL_PROVIDER": "ollama",
        "OLLAMA_MODEL": model,
        "TASK_IDS_FILE": str(task_file),
        "OUTPUT_DIR": str(output_root / condition),
        "CONDITION": condition,
        "MAX_STEPS": str(max_steps),
        "OLLAMA_NUM_CTX": env.get("OLLAMA_NUM_CTX", "16384"),
        "OLLAMA_NUM_PREDICT": env.get("OLLAMA_NUM_PREDICT", "512"),
        "RUN_ID": condition,
    })
    skill = SKILL_FOR_CONDITION.get(condition)
    if skill:
        env["SKILL_FILE"] = str(ROOT / skill)
    else:
        env.pop("SKILL_FILE", None)
    command = [sys.executable, str(ROOT / "run_alf_bench.py")]
    completed = subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True)
    log_path = output_root / "logs" / f"{condition}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(completed.stdout + "\nSTDERR\n" + completed.stderr, encoding="utf-8")
    if completed.returncode:
        raise RuntimeError(f"{condition} failed; see {log_path}\n{completed.stderr[-1000:]}")
    files = sorted((output_root / condition).glob("*.json"), key=lambda p: p.stat().st_mtime)
    if not files:
        raise RuntimeError(f"No result JSON produced for {condition}")
    return {"condition": condition, "result": str(files[-1]), "log": str(log_path)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--task-file", type=Path, default=ROOT / "configs/fixed_task_ids.json")
    parser.add_argument("--conditions", nargs="+", default=["student_baseline", "student_self_skill", "student_teacher_skill"])
    parser.add_argument("--output-root", type=Path, default=ROOT / "results")
    parser.add_argument("--max-steps", type=int, default=50)
    args = parser.parse_args()
    manifest = []
    for condition in args.conditions:
        if condition not in SKILL_FOR_CONDITION:
            raise ValueError(f"Unknown condition: {condition}")
        print(f"Running {condition} with {args.model}...", flush=True)
        manifest.append(run_condition(condition, args.model, args.task_file, args.output_root, args.max_steps))
    path = write_json(args.output_root / "experiment_manifest.json", {
        "model": args.model,
        "task_file": str(args.task_file),
        "conditions": manifest,
    })
    print(json.dumps({"manifest": str(path), "runs": manifest}, indent=2))


if __name__ == "__main__":
    main()
