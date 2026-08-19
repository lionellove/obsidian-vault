"""Generate a reusable procedural skill from successful teacher trajectories."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from experiment_common import ROOT, latest_teacher_result, rows_from

sys.path.insert(0, str(ROOT))
import run_alf_bench as bench


SYSTEM = """You are an expert instructional designer externalizing reusable procedural competence for a weaker household agent. Produce only a concise Markdown skill document. It must contain general rules, decision procedures, and recovery heuristics. Never include task IDs, benchmark names, game files, memorized object locations, or a task-to-solution lookup table."""


def compact_row(row: dict) -> str:
    lines = [f"Task family: {row.get('task_type')}", f"Goal: {row.get('task')}"]
    for step in row.get("trajectory", []):
        action = step.get("action")
        observation = step.get("next_observation") or ""
        if action:
            lines.append(f"- Action: {action}\n  Observation: {observation[:600]}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--teacher-result", type=Path)
    parser.add_argument("--student-result", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "skills/teacher_skill.md")
    parser.add_argument("--provider", default="openai")
    args = parser.parse_args()
    teacher_path = args.teacher_result or latest_teacher_result()
    teacher_rows = rows_from(teacher_path)
    samples = [row for row in teacher_rows if row.get("success")][:12]
    if args.student_result:
        student_rows = rows_from(args.student_result)
        student_by_id = {row.get("task_id"): row for row in student_rows}
        samples += [
            {"task_type": row.get("task_type"), "task": row.get("task"), "trajectory": row.get("trajectory", [])}
            for row in teacher_rows
            if not student_by_id.get(row.get("task_id"), {}).get("success")
        ][:12]
    prompt = """Study the supplied successful examples and infer the reusable procedures that explain robust household-task solving. Focus on exploration strategy, prerequisite ordering, state tracking, object acquisition, clean/heat/cool transformations, recovery after failed searches or actions, avoiding redundant actions, and selecting the next useful action from the currently admissible set.

Do not copy specific object numbers or locations. Write a self-contained skill for unseen tasks. The skill must explicitly say that current observations and admissible actions are authoritative, and must not be treated as task-specific ground truth.

Examples:

""" + "\n\n---\n\n".join(compact_row(row) for row in samples)
    bench.load_env_file()
    client = bench.ModelClient(args.provider)
    skill = client.complete(prompt, system_prompt=SYSTEM).strip()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(skill + "\n", encoding="utf-8")
    print(f"Wrote {args.output} ({len(skill)} chars) from {teacher_path}")


if __name__ == "__main__":
    main()
