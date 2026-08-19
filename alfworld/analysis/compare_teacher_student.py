"""Align teacher and student episodes and compute task-family gaps."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.experiment_common import ROOT, align_by_task_id, infer_family, rows_from, write_json


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--teacher", type=Path, required=True)
    parser.add_argument("--student", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "analysis/teacher_student_gap.json")
    args = parser.parse_args()
    teacher, student = rows_from(args.teacher), rows_from(args.student)
    aligned = align_by_task_id(teacher, student)
    counts = {"teacher_success_student_success": 0, "teacher_success_student_failure": 0, "teacher_failure_student_success": 0, "teacher_failure_student_failure": 0}
    transfer_candidates = []
    families = {}
    for key, (t, s) in aligned.items():
        ts, ss = bool(t and t.get("success")), bool(s and s.get("success"))
        label = f"teacher_{'success' if ts else 'failure'}_student_{'success' if ss else 'failure'}"
        counts[label] += 1
        family = infer_family(t or s)
        fam = families.setdefault(family, {"teacher": [], "student": []})
        fam["teacher"].append(int(ts)); fam["student"].append(int(ss))
        if ts and not ss:
            transfer_candidates.append({"task_id": t.get("task_id"), "task": t.get("task"), "task_type": family})
    family_rows = {}
    for family, values in families.items():
        teacher_rate = sum(values["teacher"]) / len(values["teacher"])
        student_rate = sum(values["student"]) / len(values["student"])
        family_rows[family] = {"n": len(values["teacher"]), "teacher_rate": teacher_rate, "student_rate": student_rate, "gap": teacher_rate - student_rate}
    result = {"teacher_result": str(args.teacher), "student_result": str(args.student), "n_aligned": len(aligned), "counts": counts, "transfer_candidates": transfer_candidates, "families": family_rows}
    write_json(args.output, result)
    md = ["# Teacher–student gap", "", f"Aligned tasks: {len(aligned)}", "", "| Family | n | Teacher | Student | Gap |", "|---|---:|---:|---:|---:|"]
    for family, row in family_rows.items():
        md.append(f"| {family} | {row['n']} | {row['teacher_rate']:.1%} | {row['student_rate']:.1%} | {row['gap']:.1%} |")
    md += ["", "## Pair counts", "", "```json", json.dumps(counts, indent=2), "```", "", f"Transfer candidates (teacher success / student failure): {len(transfer_candidates)}"]
    args.output.with_suffix(".md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
