"""Generate the matched self-skill control from student trajectories."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from experiment_common import ROOT, rows_from

sys.path.insert(0, str(ROOT))
import run_alf_bench as bench


SYSTEM = """You are creating a reusable procedural skill for a weaker household agent based only on the agent's own attempted trajectories. Produce concise Markdown with general procedures and recovery heuristics. Do not mention task IDs, benchmark names, game files, or memorize object locations. Do not write a lookup table."""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--student-result", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "skills/student_self_skill.md")
    parser.add_argument("--provider", default="openai")
    args = parser.parse_args()
    rows = rows_from(args.student_result)
    blocks = []
    for row in rows[:16]:
        block = [f"Task family: {row.get('task_type')}", f"Goal: {row.get('task')}"]
        for step in row.get("trajectory", []):
            if step.get("action"):
                block.append(f"- {step['action']} -> {(step.get('next_observation') or '')[:500]}")
        blocks.append("\n".join(block))
    prompt = """Infer reusable procedural guidance from these own attempts. Focus on systematic exploration, state tracking, prerequisites before placement, transformations, and recovery. Generalize beyond the examples; never retain specific object IDs or locations. Produce only the skill document. Current observations and admissible actions must remain authoritative.\n\nExamples:\n\n""" + "\n\n---\n\n".join(blocks)
    bench.load_env_file()
    skill = bench.ModelClient(args.provider).complete(prompt, system_prompt=SYSTEM).strip()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(skill + "\n", encoding="utf-8")
    print(f"Wrote {args.output} ({len(skill)} chars)")


if __name__ == "__main__":
    main()
