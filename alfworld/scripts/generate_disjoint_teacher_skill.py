"""Generate a task-family analysis and compile it into a reusable skill."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from experiment_common import ROOT, read_json, write_json

sys.path.insert(0, str(ROOT))
import run_alf_bench as bench


ANALYSIS_SYSTEM = (
    "You are a rigorous task-family capability analyst. Follow the supplied "
    "task_analyse.md instructions exactly. Analyze the task set jointly; "
    "do not solve individual tasks, give trajectories, or include memorized "
    "object IDs and locations. Return only the required structured analysis."
)

COMPILER_SYSTEM = (
    "You are a skill compiler for a weaker ALFWorld agent. Follow the supplied "
    "skill_compile.md instructions exactly. Compile only from the capability "
    "analysis; remove task-specific details and demonstrations. Return only "
    "the required final skill document."
)


def _task_family(task_id: str) -> str:
    mapping = {
        "pick_and_place_simple": "pick_and_place",
        "pick_clean_then_place_in_recep": "clean_and_place",
        "pick_cool_then_place_in_recep": "cool_and_place",
        "pick_two_obj_and_place": "pick_two_and_place",
    }
    for marker, family in mapping.items():
        if marker in task_id:
            return family
    return "unknown"


def _norm_id(value: str) -> str:
    return str(value or "").replace("\\", "/").rstrip("/").lower()


def validate_disjoint(task_ids: list[str], evaluation_path: Path) -> None:
    if len(task_ids) != 10 or len({_norm_id(item) for item in task_ids}) != 10:
        raise ValueError("Teacher-analysis task set must contain 10 unique task IDs")
    evaluation = read_json(evaluation_path)
    evaluation_ids = evaluation.get("task_ids", []) if isinstance(evaluation, dict) else evaluation
    overlap = {_norm_id(item) for item in task_ids} & {_norm_id(item) for item in evaluation_ids}
    if overlap:
        raise ValueError(f"Teacher-analysis tasks overlap evaluation set: {sorted(overlap)}")
    counts = Counter(_task_family(item) for item in task_ids)
    expected = Counter({"pick_and_place": 3, "clean_and_place": 3, "cool_and_place": 3, "pick_two_and_place": 1})
    if counts != expected:
        raise ValueError(f"Unexpected task-family distribution: {counts}; expected {expected}")


def load_task_descriptions(task_ids: list[str]) -> list[dict]:
    rows = []
    for index, task_id in enumerate(task_ids):
        gamefile = Path(task_id)
        if not gamefile.exists():
            raise FileNotFoundError(f"Candidate game file does not exist: {gamefile}")
        payload = json.loads(gamefile.read_text(encoding="utf-8"))
        grammar = payload.get("grammar", "")
        match = re.search(r"Your task is to:\s*([^\n]+)", grammar)
        if not match:
            raise ValueError(f"Could not extract task description from {gamefile}")
        rows.append({
            "index": index,
            "task_id": task_id,
            "task_type": _task_family(task_id),
            "task": match.group(1).strip().rstrip('"').strip(),
            "gamefile": str(gamefile),
        })
    if len(rows) != len(task_ids):
        raise RuntimeError(f"Loaded {len(rows)} task descriptions, expected {len(task_ids)}")
    return rows


def render_prompt(template: str, environment: str, rows: list[dict]) -> str:
    task_lines = []
    for row in rows:
        task_lines.append(f"- Task family: {row['task_type']}\n  Task description: {row['task']}")
    return template.replace("{ENVIRONMENT_DESCRIPTION}", environment).replace(
        "{TASK_LIST}", "\n".join(task_lines)
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-file", type=Path, default=ROOT / "configs/teacher_analysis_task_ids.json")
    parser.add_argument("--evaluation-file", type=Path, default=ROOT / "configs/fixed_task_ids.json")
    parser.add_argument("--analysis-template", type=Path, default=ROOT / "task_analyse.md")
    parser.add_argument("--compile-template", type=Path, default=ROOT / "skill_compile.md")
    parser.add_argument("--analysis-output", type=Path, default=ROOT / "results/teacher_analysis_disjoint.md")
    parser.add_argument("--skill-output", type=Path, default=ROOT / "skills/teacher_skill_compiled.md")
    parser.add_argument("--metadata-output", type=Path, default=ROOT / "results/teacher_analysis_disjoint_metadata.json")
    parser.add_argument("--provider", default="openai")
    args = parser.parse_args()

    task_payload = read_json(args.task_file)
    task_ids = task_payload.get("task_ids", []) if isinstance(task_payload, dict) else task_payload
    validate_disjoint(task_ids, args.evaluation_file)
    rows = load_task_descriptions(task_ids)

    environment = """ALFWorld text household environment. The agent receives a natural-language task, textual observations of the current room and reachable objects, and a list of currently admissible text actions. The environment is sequential and partially observable: navigation and inspection reveal facts, manipulation changes object state and location, and the admissible action set changes with state. Reliable solving requires grounding every action in the current observation and admissible-action list, tracking object possession/location/state, respecting prerequisites such as cleaning or cooling before placement, verifying state transitions from feedback, recovering from failed assumptions, and stopping only after the task goal is confirmed."""
    rows_for_prompt = [{"task_type": row["task_type"], "task": row["task"]} for row in rows]
    analysis_template = args.analysis_template.read_text(encoding="utf-8")
    compile_template = args.compile_template.read_text(encoding="utf-8")
    analysis_prompt = render_prompt(analysis_template, environment, rows_for_prompt)

    bench.load_env_file()
    client = bench.ModelClient(args.provider)
    analysis = client.complete(analysis_prompt, system_prompt=ANALYSIS_SYSTEM).strip()
    analysis_usage = dict(client.last_usage)
    if not analysis:
        raise RuntimeError("DeepSeek returned an empty task analysis")
    compile_prompt = compile_template.replace("{CAPABILITY_ANALYSIS}", analysis)
    skill = client.complete(compile_prompt, system_prompt=COMPILER_SYSTEM).strip()
    if not skill:
        raise RuntimeError("DeepSeek returned an empty compiled skill")

    args.analysis_output.parent.mkdir(parents=True, exist_ok=True)
    args.skill_output.parent.mkdir(parents=True, exist_ok=True)
    args.metadata_output.parent.mkdir(parents=True, exist_ok=True)
    args.analysis_output.write_text(analysis + "\n", encoding="utf-8")
    args.skill_output.write_text(skill + "\n", encoding="utf-8")
    metadata = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "provider": client.provider,
        "model": client.model,
        "task_file": str(args.task_file),
        "evaluation_file": str(args.evaluation_file),
        "task_ids": task_ids,
        "task_families": Counter(row["task_type"] for row in rows),
        "task_descriptions": rows_for_prompt,
        "analysis_template": str(args.analysis_template),
        "compile_template": str(args.compile_template),
        "analysis_output": str(args.analysis_output),
        "skill_output": str(args.skill_output),
        "analysis_usage": analysis_usage,
        "skill_usage": dict(client.last_usage),
        "skill_chars": len(skill),
        "analysis_chars": len(analysis),
    }
    write_json(args.metadata_output, metadata)
    print(json.dumps({
        "analysis_output": str(args.analysis_output),
        "skill_output": str(args.skill_output),
        "metadata_output": str(args.metadata_output),
        "task_count": len(rows),
        "task_families": dict(Counter(row["task_type"] for row in rows)),
        "analysis_chars": len(analysis),
        "skill_chars": len(skill),
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
