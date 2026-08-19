"""Compute paired task-level transfer metrics and an exact McNemar test."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from scripts.experiment_common import ROOT, align_by_task_id, rows_from, result_summary, write_json


def wilson(successes: int, n: int, z: float = 1.96):
    if not n: return [0.0, 0.0]
    p = successes / n; d = 1 + z*z/n
    center = (p + z*z/(2*n)) / d
    half = z * math.sqrt((p*(1-p) + z*z/(4*n))/n) / d
    return [max(0, center-half), min(1, center+half)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--teacher-skill", type=Path, required=True)
    parser.add_argument("--self-skill", type=Path)
    parser.add_argument("--teacher", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "analysis/transfer_metrics.json")
    args = parser.parse_args()
    paths = [args.baseline, args.teacher_skill] + ([args.self_skill] if args.self_skill else []) + ([args.teacher] if args.teacher else [])
    aligned = align_by_task_id(*(rows_from(path) for path in paths))
    base = rows_from(args.baseline); skill = rows_from(args.teacher_skill)
    pairs = [(bool(rows[0] and rows[0].get("success")), bool(rows[1] and rows[1].get("success"))) for rows in aligned.values()]
    rescued = sum(not a and b for a, b in pairs); regressions = sum(a and not b for a, b in pairs)
    b01, b10 = rescued, regressions
    mcnemar_p = 1.0 if b01 + b10 == 0 else (2 ** (-(b01 + b10)) * sum(math.comb(b01 + b10, k) for k in range(0, min(b01, b10) + 1)) * 2)
    output = {"summaries": {str(path): result_summary(rows_from(path)) for path in paths}, "n_aligned": len(aligned), "rescued_tasks": rescued, "regressions": regressions, "absolute_gain": (sum(b for _, b in pairs) - sum(a for a, _ in pairs)) / len(pairs) if pairs else 0, "baseline_ci95": wilson(sum(a for a, _ in pairs), len(pairs)), "teacher_skill_ci95": wilson(sum(b for _, b in pairs), len(pairs)), "mcnemar_exact_two_sided_p": min(1.0, mcnemar_p), "transfer_ratio": None}
    if args.teacher:
        teacher_rate = output["summaries"][str(args.teacher)]["success_rate"]
        baseline_rate = output["summaries"][str(args.baseline)]["success_rate"]
        skill_rate = output["summaries"][str(args.teacher_skill)]["success_rate"]
        if teacher_rate > baseline_rate:
            output["transfer_ratio"] = (skill_rate - baseline_rate) / (teacher_rate - baseline_rate)
    write_json(args.output, output)
    print(output)


if __name__ == "__main__":
    main()
