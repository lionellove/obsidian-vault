"""Create the final compact Markdown report from experiment JSON artifacts."""

from __future__ import annotations

import argparse
from pathlib import Path

from scripts.experiment_common import ROOT, read_json, rows_from, result_summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--self-skill", type=Path, required=True)
    parser.add_argument("--teacher-skill", type=Path, required=True)
    parser.add_argument("--teacher", type=Path, required=True)
    parser.add_argument("--transfer", type=Path, default=ROOT / "analysis/transfer_metrics.json")
    parser.add_argument("--gap", type=Path, default=ROOT / "analysis/teacher_student_gap.json")
    parser.add_argument("--likeness", type=Path, default=ROOT / "analysis/teacher_likeness.json")
    parser.add_argument("--output", type=Path, default=ROOT / "reports/transfer_results.md")
    args = parser.parse_args()
    paths = [("Student", args.baseline), ("Student + Self Skill", args.self_skill), ("Student + Teacher Skill", args.teacher_skill), ("Teacher", args.teacher)]
    lines = ["# ALFWorld teacher-to-student skill transfer", "", "## Performance", "", "| Condition | Success | Gain vs baseline | Avg steps | Format failure |", "|---|---:|---:|---:|---:|"]
    base = result_summary(rows_from(args.baseline))["success_rate"]
    for name, path in paths:
        summary = result_summary(rows_from(path))
        gain = summary["success_rate"] - base if name != "Student" else 0
        lines.append(f"| {name} | {summary['success_rate']:.1%} | {gain:+.1%} | {summary['avg_steps']:.1f} | {summary['format_failure_rate']:.1%} |")
    transfer = read_json(args.transfer) if args.transfer.exists() else {}
    lines += ["", "## Paired transfer", "", f"- Rescued tasks (0 → 1): {transfer.get('rescued_tasks', 'n/a')}", f"- Regressions (1 → 0): {transfer.get('regressions', 'n/a')}", f"- Absolute paired gain: {transfer.get('absolute_gain', 0):.1%}", f"- Exact McNemar p-value: {transfer.get('mcnemar_exact_two_sided_p', 'n/a')}", f"- Descriptive transfer ratio: {transfer.get('transfer_ratio', 'n/a')}"]
    if args.gap.exists():
        gap = read_json(args.gap)
        lines += ["", "## Task-family alignment", "", "| Family | n | Teacher | Student | Gap |", "|---|---:|---:|---:|---:|"]
        for family, row in gap.get("families", {}).items(): lines.append(f"| {family} | {row['n']} | {row['teacher_rate']:.1%} | {row['student_rate']:.1%} | {row['gap']:.1%} |")
    if args.likeness.exists():
        likeness = read_json(args.likeness)
        lines += ["", "## Observable teacher-likeness", "", f"- Baseline event-sequence similarity: {likeness.get('mean_baseline_similarity', 0):.3f}", f"- Teacher-skill event-sequence similarity: {likeness.get('mean_teacher_skill_similarity', 0):.3f}"]
    lines += ["", "## Interpretation", "", "Performance improvement alone is not sufficient evidence of capability transfer. The claim is stronger only if teacher skill exceeds self-skill, gains align with teacher-advantage families, failure modes decrease, and rescued trajectories become closer to teacher procedures at the action/event level."]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
