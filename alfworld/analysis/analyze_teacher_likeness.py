"""Compare semantic event-stage ordering without comparing chain-of-thought text."""

from __future__ import annotations

import argparse
from pathlib import Path

from scripts.experiment_common import ROOT, align_by_task_id, rows_from, write_json
from extract_behavioral_events import extract


def collapse(events):
    out = []
    for event in events:
        name = event["event"]
        if name != (out[-1] if out else None): out.append(name)
    return out


def lcs(a, b):
    table = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i, x in enumerate(a, 1):
        for j, y in enumerate(b, 1):
            table[i][j] = table[i-1][j-1] + 1 if x == y else max(table[i-1][j], table[i][j-1])
    return table[-1][-1]


def similarity(a, b):
    return lcs(a, b) / max(1, len(a), len(b))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--teacher", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--teacher-skill", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "analysis/teacher_likeness.json")
    args = parser.parse_args()
    teacher = rows_from(args.teacher); baseline = rows_from(args.baseline); skill = rows_from(args.teacher_skill)
    values = []
    rescued = []
    for task_id, (t, b, s) in align_by_task_id(teacher, baseline, skill).items():
        if not t or not b or not s or not t.get("success"):
            continue
        ts = collapse([e for e in extract(t)["events"] if e["event"] != "INVALID_ACTION"])
        bs = collapse([e for e in extract(b)["events"] if e["event"] != "INVALID_ACTION"])
        ss = collapse([e for e in extract(s)["events"] if e["event"] != "INVALID_ACTION"])
        row = {"task_id": t.get("task_id"), "teacher_similarity": similarity(ts, ts), "baseline_similarity": similarity(bs, ts), "teacher_skill_similarity": similarity(ss, ts), "teacher_events": ts, "baseline_events": bs, "teacher_skill_events": ss}
        values.append(row)
        if not b.get("success") and s.get("success"): rescued.append(row)
    mean = lambda key: sum(row[key] for row in values) / len(values) if values else 0.0
    output = {"n": len(values), "mean_baseline_similarity": mean("baseline_similarity"), "mean_teacher_skill_similarity": mean("teacher_skill_similarity"), "rescued": rescued, "per_task": values}
    write_json(args.output, output)
    print(output)


if __name__ == "__main__":
    main()
